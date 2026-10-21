import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..deps import DB, Principal, deny, require
from ..domain import entity_resolution
from ..models import (
    Case,
    Employment,
    IdentityLink,
    ImportBatch,
    ImportRecord,
    MergeCandidate,
    Payment,
    RiskAssessment,
    Taxpayer,
    TaxObligation,
    TaxReturn,
)
from ..permissions import P
from ..schemas import (
    AssessmentSummary,
    CaseSummary,
    IdentityLinkOut,
    MergeCandidateOut,
    MergeDecisionIn,
    ObligationOut,
    Page,
    PaymentOut,
    ReturnOut,
    Taxpayer360,
    TaxpayerSummary,
)
from ..domain.scoring import feed_freshness, DEFAULT_THRESHOLDS
from ..config import today
from ._common import Limit, Offset, get_scoped, log, paginate

router = APIRouter(prefix="/v1", tags=["taxpayers & data quality"])


def latest_assessments(db, tenant_id, taxpayer_ids) -> dict[uuid.UUID, RiskAssessment]:
    if not taxpayer_ids:
        return {}
    rows = db.execute(
        select(RiskAssessment).where(
            RiskAssessment.tenant_id == tenant_id, RiskAssessment.taxpayer_id.in_(taxpayer_ids),
            RiskAssessment.superseded_by_id.is_(None),
        ).order_by(RiskAssessment.evaluation_time)
    ).scalars()
    out: dict[uuid.UUID, RiskAssessment] = {}
    for a in rows:
        cur = out.get(a.taxpayer_id)
        if cur is None or a.score > cur.score:
            out[a.taxpayer_id] = a
    return out


def summary(tp: Taxpayer, latest: dict) -> TaxpayerSummary:
    a = latest.get(tp.id)
    return TaxpayerSummary.model_validate(tp).model_copy(
        update={"latest_score": a.score if a else None, "latest_confidence": a.confidence if a else None}
    )


@router.get("/taxpayers", response_model=Page[TaxpayerSummary])
def search_taxpayers(
    db: DB, principal: Annotated[Principal, Depends(require(P.TAXPAYERS_READ))],
    q: str | None = None, lga: str | None = None, sector: str | None = None, taxpayer_type: str | None = None,
    registration_status: str | None = None, limit: int = Limit, offset: int = Offset,
) -> Page[TaxpayerSummary]:
    stmt = select(Taxpayer).where(
        Taxpayer.tenant_id == principal.tenant_id, Taxpayer.merged_into_id.is_(None), Taxpayer.deleted_at.is_(None)
    ).order_by(Taxpayer.name)
    if q:
        stmt = stmt.where(func.lower(Taxpayer.name).contains(q.lower()))
    for col, val in ((Taxpayer.lga, lga), (Taxpayer.sector, sector), (Taxpayer.taxpayer_type, taxpayer_type),
                     (Taxpayer.registration_status, registration_status)):
        if val:
            stmt = stmt.where(col == val)
    rows, total = paginate(db, stmt, limit, offset)
    tps = [r[0] for r in rows]
    latest = latest_assessments(db, principal.tenant_id, [t.id for t in tps])
    log(db, principal, "taxpayer.search", "taxpayer", None, query=bool(q), lga=lga, sector=sector, results=len(tps))
    db.commit()
    return Page(items=[summary(t, latest) for t in tps], total=total, limit=limit, offset=offset)


@router.get("/taxpayers/{taxpayer_id}", response_model=Taxpayer360, summary="Taxpayer 360 (access is logged)")
def taxpayer_360(taxpayer_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.TAXPAYERS_READ))]) -> Taxpayer360:
    tp = get_scoped(db, Taxpayer, taxpayer_id, principal)
    sensitive = principal.can(P.TAXPAYERS_READ_SENSITIVE)
    links = db.execute(select(IdentityLink).where(IdentityLink.taxpayer_id == tp.id)).scalars().all()
    identifiers = [
        IdentityLinkOut(identifier_type=link.identifier_type,
                        value=link.masked_value if not sensitive else f"{link.masked_value} (hash {link.hashed_identifier[:12]}…)",
                        match_confidence=link.match_confidence, source_ref=link.source_ref if sensitive else None)
        for link in links
    ]
    emps = db.execute(
        select(Employment, Taxpayer).join(Taxpayer, Taxpayer.id == Employment.employer_id).where(Employment.employee_id == tp.id)
    ).all() + db.execute(
        select(Employment, Taxpayer).join(Taxpayer, Taxpayer.id == Employment.employee_id).where(Employment.employer_id == tp.id)
    ).all()
    employer_links = [
        {"relationship": "employer" if e.employer_id == other.id else "employee", "taxpayer_id": str(other.id),
         "name": other.name, "start_date": e.start_date.isoformat(), "end_date": e.end_date.isoformat() if e.end_date else None}
        for e, other in emps
    ][:200]
    obligations = db.execute(
        select(TaxObligation).where(TaxObligation.taxpayer_id == tp.id).order_by(TaxObligation.period.desc())
    ).scalars().all()
    returns = db.execute(select(TaxReturn).where(TaxReturn.taxpayer_id == tp.id).order_by(TaxReturn.period.desc())).scalars().all()
    payments = db.execute(select(Payment).where(Payment.taxpayer_id == tp.id).order_by(Payment.payment_date.desc())).scalars().all()
    assessments = db.execute(
        select(RiskAssessment).where(RiskAssessment.taxpayer_id == tp.id).order_by(RiskAssessment.evaluation_time.desc()).limit(20)
    ).scalars().all()
    cases = db.execute(select(Case).where(Case.taxpayer_id == tp.id).order_by(Case.created_at.desc())).scalars().all()
    latest = latest_assessments(db, principal.tenant_id, [tp.id])
    log(db, principal, "taxpayer.view", "taxpayer", tp.id, sensitive_fields=sensitive)
    db.commit()
    return Taxpayer360(
        taxpayer=summary(tp, latest), tax_residence=tp.tax_residence, closed_on=tp.closed_on, registered_on=tp.registered_on,
        source=f"{tp.source_system}:{tp.source_record_id}", merged_into_id=tp.merged_into_id, identifiers=identifiers,
        employer_links=employer_links,
        obligations=[ObligationOut.model_validate(o) for o in obligations],
        returns=[ReturnOut.model_validate(r) for r in returns],
        payments=[PaymentOut.model_validate(p) for p in payments],
        assessments=[AssessmentSummary.model_validate(a).model_copy(update={"taxpayer_name": tp.name}) for a in assessments],
        cases=[CaseSummary.model_validate(c).model_copy(update={
            "taxpayer_name": tp.name, "sla_breached": (c.closed_at.date() if c.closed_at else today()) > c.sla_due})
            for c in cases],
    )


# --- data quality workbench --------------------------------------------------------------------


@router.get("/data-quality/summary")
def data_quality_summary(db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_READ))]) -> dict:
    t = principal.tenant_id
    feeds = feed_freshness(db, t)
    stale_after = DEFAULT_THRESHOLDS["feed_staleness_days"]
    connectors = []
    for ds, extracted in feeds.items():
        last = db.execute(
            select(ImportBatch).where(ImportBatch.tenant_id == t, ImportBatch.dataset == ds).order_by(ImportBatch.created_at.desc())
        ).scalars().first()
        age = (today() - date.fromisoformat(extracted)).days if extracted else None
        connectors.append({
            "dataset": ds, "source_system": last.source_system if last else None, "last_extracted_at": extracted,
            "age_days": age, "stale": age is None or age > stale_after,
            "last_batch_status": last.status if last else None, "last_batch_id": str(last.id) if last else None,
        })
    rec_counts = dict(
        db.execute(select(ImportRecord.status, func.count()).where(ImportRecord.tenant_id == t).group_by(ImportRecord.status)).all()
    )
    unresolved_quarantine = db.execute(
        select(func.count()).where(ImportRecord.tenant_id == t, ImportRecord.status == "quarantined")
    ).scalar_one()
    merges = dict(
        db.execute(select(MergeCandidate.status, func.count()).where(MergeCandidate.tenant_id == t).group_by(MergeCandidate.status)).all()
    )
    unreconciled = db.execute(
        select(func.count()).where(ImportBatch.tenant_id == t, ImportBatch.reconciliation_status == "unreconciled")
    ).scalar_one()
    return {"connectors": connectors, "record_status_counts": rec_counts, "quarantined_open": unresolved_quarantine,
            "merge_candidates": merges, "unreconciled_batches": unreconciled, "stale_after_days": stale_after}


@router.get("/data-quality/quarantine", response_model=Page[dict])
def quarantine(db: DB, principal: Annotated[Principal, Depends(require(P.DATA_QUALITY_REVIEW))],
               limit: int = Limit, offset: int = Offset) -> Page[dict]:
    q = (select(ImportRecord, ImportBatch).join(ImportBatch, ImportBatch.id == ImportRecord.batch_id)
         .where(ImportRecord.tenant_id == principal.tenant_id, ImportRecord.status == "quarantined")
         .order_by(ImportRecord.created_at.desc()))
    rows, total = paginate(db, q, limit, offset)
    items = [{"id": str(r.id), "batch_id": str(b.id), "dataset": b.dataset, "source_system": b.source_system,
              "row_number": r.row_number, "source_record_id": r.source_record_id, "errors": r.errors} for r, b in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/merge-candidates", response_model=Page[MergeCandidateOut])
def merge_candidates(db: DB, principal: Annotated[Principal, Depends(require(P.DATA_QUALITY_REVIEW))],
                     status: str | None = None, limit: int = Limit, offset: int = Offset) -> Page[MergeCandidateOut]:
    q = select(MergeCandidate).where(MergeCandidate.tenant_id == principal.tenant_id).order_by(MergeCandidate.confidence.desc())
    if status:
        q = q.where(MergeCandidate.status == status)
    rows, total = paginate(db, q, limit, offset)
    ids = {i for (m,) in rows for i in (m.survivor_id, m.duplicate_id)}
    names = dict(db.execute(select(Taxpayer.id, Taxpayer.name).where(Taxpayer.id.in_(ids))).all()) if ids else {}
    items = [MergeCandidateOut.model_validate(m).model_copy(update={"survivor_name": names.get(m.survivor_id),
                                                                    "duplicate_name": names.get(m.duplicate_id)}) for (m,) in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/merge-candidates/scan")
def scan_candidates(db: DB, principal: Annotated[Principal, Depends(require(P.MERGES_PROPOSE))]) -> dict:
    n = entity_resolution.find_candidates(db, principal.tenant_id)
    log(db, principal, "merge.scan", "merge_candidate", None, created=n)
    db.commit()
    return {"created": n}


@router.post("/merge-candidates/{candidate_id}/decision", response_model=MergeCandidateOut)
def merge_decision(candidate_id: uuid.UUID, body: MergeDecisionIn, db: DB,
                   principal: Annotated[Principal, Depends(require(P.MERGES_PROPOSE))]) -> MergeCandidateOut:
    cand = get_scoped(db, MergeCandidate, candidate_id, principal)
    try:
        if body.decision == "propose":
            entity_resolution.propose(db, cand, principal.user_id, principal.role, body.reason)
        else:
            if not principal.can(P.MERGES_APPROVE):
                raise deny(db, principal, f"merge.{body.decision}", "merge_candidate", candidate_id,
                           "Missing permission: merges.approve")
            fn = {"approve": entity_resolution.approve, "reject": entity_resolution.reject,
                  "rollback": entity_resolution.rollback}[body.decision]
            fn(db, cand, principal.user_id, principal.role, body.reason)
    except entity_resolution.FourEyesViolation as exc:
        db.rollback()
        raise deny(db, principal, "merge.approve", "merge_candidate", candidate_id, str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    names = dict(db.execute(select(Taxpayer.id, Taxpayer.name).where(Taxpayer.id.in_([cand.survivor_id, cand.duplicate_id]))).all())
    return MergeCandidateOut.model_validate(cand).model_copy(
        update={"survivor_name": names.get(cand.survivor_id), "duplicate_name": names.get(cand.duplicate_id)})
