from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import not_found
from ..models import (
    Assessment,
    CaseRecord,
    Employer,
    IdentityMatch,
    Payment,
    ReturnFiling,
    RiskFinding,
    TaxObligation,
    Taxpayer,
    TaxpayerIdentifier,
)
from ..security import crypto
from ..security.auth import Principal, declared_purpose, get_db, require
from ..serializers import active_cases, finding_summary, rule_titles
from ..services import analytics, identity

router = APIRouter(prefix="/api/v1/taxpayers", tags=["taxpayer intelligence"])


def _duplicate_warnings(db: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in db.execute(
        select(RiskFinding).where(
            RiskFinding.rule_code == "DAT-001", RiskFinding.status.in_(["review_required", "validated"])
        )
    ).scalars():
        a, b = f.subject_id.split("~")
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return out


@router.get("")
def search(
    q: str | None = None,
    lga: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require("taxpayers:read")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Employer).where(Employer.is_current)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Employer.display_name.ilike(like),
                Employer.source_employer_id.ilike(like),
                Employer.linked_taxpayer_ref.ilike(like),
            )
        )
    if lga:
        stmt = stmt.where(Employer.lga_code == lga)
    if principal.lga_scope:
        stmt = stmt.where(Employer.lga_code.in_(principal.lga_scope))
    employers = list(db.execute(stmt.order_by(Employer.source_employer_id)).scalars())
    total = len(employers)
    employers = employers[(page - 1) * page_size : page * page_size]
    taxpayers = {t.id: t for t in db.execute(select(Taxpayer).where(Taxpayer.is_current)).scalars()}
    matches = identity.latest_matches(db)
    dupes = _duplicate_warnings(db)
    obligations: dict[str, list[TaxObligation]] = {}
    for o in db.execute(select(TaxObligation).where(TaxObligation.is_current)).scalars():
        obligations.setdefault(o.taxpayer_ref, []).append(o)
    open_counts: dict[str, int] = {}
    for ref in db.execute(
        select(RiskFinding.employer_ref).where(
            RiskFinding.status.in_(
                ["review_required", "approved_for_treatment", "treated", "outcome_pending"]
            ),
            RiskFinding.superseded_by_id.is_(None),
        )
    ).scalars():
        if ref:
            open_counts[ref] = open_counts.get(ref, 0) + 1
    items = []
    for e in employers:
        tp = taxpayers.get(e.taxpayer_id) if e.taxpayer_id else None
        m = matches.get(e.source_employer_id)
        obls = obligations.get(e.source_employer_id, [])
        items.append(
            {
                "employer_ref": e.source_employer_id,
                "name": e.display_name,
                "lga": e.lga_code,
                "sector": e.sector,
                "segment": e.segment,
                "status": e.status,
                "taxpayer_ref": tp.source_taxpayer_id if tp else None,
                "identity": {"status": m.status if m else "none", "confidence": m.confidence if m else None},
                "duplicate_warning": dupes.get(tp.source_taxpayer_id, []) if tp else [],
                "tax_types": sorted({o.tax_type for o in obls if o.status == "active"}),
                "obligation_status": "no_obligation_record"
                if not obls
                else ",".join(sorted({o.status for o in obls})),
                "open_findings": open_counts.get(e.source_employer_id, 0),
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{ref}")
def taxpayer_360(
    ref: str, principal: Principal = Depends(require("taxpayers:read")), db: Session = Depends(get_db)
) -> dict:
    emp = db.execute(
        select(Employer).where(Employer.is_current, Employer.source_employer_id == ref)
    ).scalar_one_or_none()
    if emp is None or (principal.lga_scope and emp.lga_code not in principal.lga_scope):
        raise not_found("Taxpayer")
    tp = db.get(Taxpayer, emp.taxpayer_id) if emp.taxpayer_id else None
    ids = (
        list(
            db.execute(
                select(TaxpayerIdentifier).where(
                    TaxpayerIdentifier.taxpayer_id == tp.id, TaxpayerIdentifier.is_current
                )
            ).scalars()
        )
        if tp
        else []
    )
    match = identity.latest_matches(db).get(ref)
    history = list(
        db.execute(
            select(IdentityMatch)
            .where(IdentityMatch.method_detail["employer_ref"].astext == ref)
            .order_by(IdentityMatch.created_at)
        ).scalars()
    )
    obligations = list(
        db.execute(
            select(TaxObligation).where(TaxObligation.is_current, TaxObligation.taxpayer_ref == ref)
        ).scalars()
    )
    filings = list(
        db.execute(
            select(ReturnFiling)
            .where(ReturnFiling.is_current, ReturnFiling.employer_ref == ref)
            .order_by(ReturnFiling.period_code)
        ).scalars()
    )
    payments = list(
        db.execute(
            select(Payment).where(Payment.is_current, Payment.employer_ref == ref).order_by(Payment.paid_at)
        ).scalars()
    )
    assessments = list(
        db.execute(select(Assessment).where(Assessment.is_current, Assessment.employer_ref == ref)).scalars()
    )
    fnds = list(
        db.execute(
            select(RiskFinding)
            .where(RiskFinding.employer_ref == ref)
            .order_by(RiskFinding.period_code.desc(), RiskFinding.rule_code)
        ).scalars()
    )
    cases = list(db.execute(select(CaseRecord).where(CaseRecord.employer_ref == ref)).scalars())
    titles = rule_titles(db)
    active = active_cases(db, [f.id for f in fnds])
    periods = []
    run = analytics.latest_run(db)
    if run is not None:
        for r in analytics._employer_records(db, run):
            if r["subject_id"] != ref:
                continue
            f = r["facts"]
            periods.append(
                {
                    "period": r["period"],
                    "obligation_status": f["obligation_status"],
                    "return_due_at": f["return_due_at"],
                    "accepted_at": f["accepted_at"],
                    "filing_status": "unknown_no_coverage"
                    if not r["quality"]["coverage"]["filing"]
                    else "not_due"
                    if not f["return_due_passed"]
                    else "accepted_on_time"
                    if f["accepted_filing_count"] and not f["filing_late_days"]
                    else "accepted_late"
                    if f["accepted_filing_count"]
                    else "pending_processing"
                    if f["processing_window_open"]
                    else "missing",
                    "payment_status": "unknown_no_coverage"
                    if not r["quality"]["coverage"]["payment"]
                    else "possible_unallocated_receipt"
                    if f["possible_unallocated_receipt"]
                    else "not_due"
                    if not f["payment_due_passed"]
                    else "paid_on_time"
                    if f["settled_payment_count"] and not f["payment_late_days"]
                    else "paid_late"
                    if f["settled_payment_count"]
                    else "missing",
                    "declared_payable": f["declared_payable"],
                    "paid": f["paid_allocated_total"],
                    "residual": f["residual_amount"],
                    "legal_version": (r.get("legal_versions") or {})
                    .get("PAYE_EMPLOYER_MONTHLY_RETURN", {})
                    .get("label"),
                    "holds": [
                        k
                        for k in ("source_conflict", "quarantined_period_records", "legal_hold", "disputed")
                        if f.get(k)
                    ],
                }
            )
    reporting_evidence = [x.employee_count for x in filings if x.employee_count is not None]
    audit.record(db, principal, "taxpayer.viewed", f"employer:{ref}", {})
    return {
        "employer": {
            "ref": emp.source_employer_id,
            "name": emp.display_name,
            "lga": emp.lga_code,
            "office": emp.office_code,
            "sector": emp.sector,
            "segment": emp.segment,
            "status": emp.status,
            "activity_from": emp.activity_from.isoformat() if emp.activity_from else None,
            "activity_to": emp.activity_to.isoformat() if emp.activity_to else None,
            "source_record": str(emp.source_record_id),
        },
        "taxpayer": {
            "ref": tp.source_taxpayer_id,
            "name": tp.display_name,
            "type": tp.taxpayer_type,
            "status": tp.status,
            "jurisdiction": tp.jurisdiction_code,
            "lga": tp.lga_code,
            "identifiers": [
                {"type": i.identifier_type, "masked": i.masked, "verification": i.verification_status}
                for i in ids
            ],
        }
        if tp
        else None,
        "identity": {
            "status": match.status if match else "none",
            "confidence": match.confidence if match else None,
            "match_type": match.match_type if match else None,
            "history": [
                {
                    "status": m.status,
                    "type": m.match_type,
                    "confidence": m.confidence,
                    "reviewer": m.reviewer,
                    "at": m.created_at.isoformat(),
                }
                for m in history
            ],
        },
        "duplicate_warning": _duplicate_warnings(db).get(tp.source_taxpayer_id, []) if tp else [],
        "obligations": [
            {
                "tax_type": o.tax_type,
                "type": o.obligation_type,
                "status": o.status,
                "effective_from": o.effective_from.isoformat(),
                "effective_to": o.effective_to.isoformat() if o.effective_to else None,
                "exemption": o.exemption_status,
                "source": f"src:obligation:{o.natural_key}",
            }
            for o in obligations
        ],
        "obligation_summary": "no_obligation_record" if not obligations else "recorded",
        "periods": periods,
        "filings": [
            {
                "ref": x.filing_reference,
                "source": x.source_name,
                "period": x.period_code,
                "status": x.status,
                "submitted_at": x.submitted_at.isoformat() if x.submitted_at else None,
                "accepted_at": x.accepted_at.isoformat() if x.accepted_at else None,
                "amount_declared": float(x.amount_declared) if x.amount_declared is not None else None,
            }
            for x in filings
        ],
        "payments": [
            {
                "ref": p.payment_reference,
                "period": p.period_code,
                "paid_at": p.paid_at.isoformat(),
                "amount": float(p.amount),
                "reversal_status": p.reversal_status,
                "allocation_status": p.allocation_status,
                "settlement_status": p.settlement_status,
            }
            for p in payments
        ],
        "assessments": [
            {
                "ref": a.assessment_ref,
                "period": a.period_code,
                "amount": float(a.amount),
                "outstanding": float(a.outstanding_amount),
                "status": a.status,
                "appeal_status": a.appeal_status,
                "served_on": a.served_on.isoformat() if a.served_on else None,
            }
            for a in assessments
        ],
        "reporting_risk": {
            "status": "unknown" if not reporting_evidence else "evidence_available",
            "note": "No employee-count evidence: reporting risk is unknown, not zero."
            if not reporting_evidence
            else f"{len(reporting_evidence)} returns carry employee counts",
        },
        "findings": [finding_summary(f, {ref: emp.display_name}, titles, active.get(f.id)) for f in fnds],
        "cases": [
            {"id": str(c.id), "ref": c.case_ref, "stage": c.stage, "treatment": c.treatment} for c in cases
        ],
        "label": "Risk indicator, not finding of evasion",
    }


@router.post("/{ref}/identifiers/reveal")
def reveal(
    ref: str,
    purpose: str | None = Header(default=None, alias="X-Purpose"),
    principal: Principal = Depends(require("taxpayers:reveal_identifiers")),
    db: Session = Depends(get_db),
) -> dict:
    p = declared_purpose(principal, purpose)
    emp = db.execute(
        select(Employer).where(Employer.is_current, Employer.source_employer_id == ref)
    ).scalar_one_or_none()
    if emp is None or emp.taxpayer_id is None:
        raise not_found("Taxpayer")
    ids = list(
        db.execute(
            select(TaxpayerIdentifier).where(
                TaxpayerIdentifier.taxpayer_id == emp.taxpayer_id, TaxpayerIdentifier.is_current
            )
        ).scalars()
    )
    audit.record(
        db, principal, "taxpayer.identifier_revealed", f"employer:{ref}", {"count": len(ids)}, purpose=p
    )
    return {
        "identifiers": [
            {
                "type": i.identifier_type,
                "value": crypto.decrypt(i.encrypted_value, str(i.taxpayer_id).encode()).decode(),
            }
            for i in ids
        ],
        "purpose": p,
    }
