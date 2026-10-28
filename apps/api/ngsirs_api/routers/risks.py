from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from risk_engine.states import OPEN_FINDING_STATES

from .. import audit
from ..errors import not_found
from ..idempotency import run_once
from ..models import RiskFinding
from ..schemas import FindingDetail, FindingPage, OverrideRequest, ReviewRequest
from ..security.auth import Principal, get_db, require
from ..serializers import active_cases, employer_names, finding_detail, finding_summary, rule_titles
from ..services import evaluation, findings

router = APIRouter(prefix="/api/v1/risks", tags=["risk register"])


def scoped(q, principal: Principal):  # type: ignore[no-untyped-def]
    if principal.lga_scope:
        q = q.where(RiskFinding.lga_code.in_(principal.lga_scope))
    return q


def load(db: Session, principal: Principal, finding_id: uuid.UUID) -> RiskFinding:
    f = db.get(RiskFinding, finding_id)
    if f is None or (principal.lga_scope and f.lga_code not in principal.lga_scope):
        raise not_found("Finding")
    return f


@router.get("", response_model=FindingPage)
def list_risks(
    tax_type: str | None = "PAYE",
    lga: str | None = None,
    status: str | None = None,
    rule: str | None = None,
    signal_class: str | None = None,
    band: str | None = None,
    period: str | None = None,
    q: str | None = None,
    open_only: bool = True,
    hold: str | None = Query(None, pattern="^(data_hold|legal_hold|disputed|none)$"),
    employer: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(require("risks:read")),
    db: Session = Depends(get_db),
) -> dict:
    stmt = scoped(select(RiskFinding).where(RiskFinding.superseded_by_id.is_(None)), principal)
    if tax_type:
        stmt = stmt.where(RiskFinding.tax_type == tax_type)
    if lga:
        stmt = stmt.where(RiskFinding.lga_code == lga)
    if status:
        stmt = stmt.where(RiskFinding.status.in_(status.split(",")))
    elif open_only:
        stmt = stmt.where(RiskFinding.status.in_(OPEN_FINDING_STATES))
    if rule:
        stmt = stmt.where(RiskFinding.rule_code.in_(rule.split(",")))
    if signal_class:
        stmt = stmt.where(RiskFinding.signal_class == signal_class)
    if band:
        stmt = stmt.where(RiskFinding.priority_band == band)
    if period:
        stmt = stmt.where(RiskFinding.period_code == period)
    if employer:
        stmt = stmt.where(RiskFinding.employer_ref == employer)
    if hold == "data_hold":
        stmt = stmt.where(RiskFinding.data_hold.is_(True))
    elif hold == "legal_hold":
        stmt = stmt.where(RiskFinding.legal_hold.is_(True))
    elif hold == "disputed":
        stmt = stmt.where(RiskFinding.disputed.is_(True))
    elif hold == "none":
        stmt = stmt.where(
            RiskFinding.data_hold.is_(False),
            RiskFinding.legal_hold.is_(False),
            RiskFinding.disputed.is_(False),
        )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                RiskFinding.subject_id.ilike(like),
                RiskFinding.finding_ref.ilike(like),
                RiskFinding.employer_ref.ilike(like),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(
        db.execute(
            stmt.order_by(
                RiskFinding.priority.desc().nulls_last(),
                RiskFinding.likelihood.desc().nulls_last(),
                RiskFinding.period_code.desc(),
                RiskFinding.finding_ref,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    names = employer_names(db, {f.employer_ref for f in rows})
    titles = rule_titles(db)
    cases = active_cases(db, [f.id for f in rows])
    return {
        "items": [finding_summary(f, names, titles, cases.get(f.id)) for f in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "denominator_note": f"{total} findings match the filters. Ordering uses the priority index (4 x L x C) "
        "for queue ordering only; unknown-exposure findings follow, ordered by likelihood.",
    }


@router.get("/{finding_id}", response_model=FindingDetail)
def get_risk(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require("risks:read")),
    db: Session = Depends(get_db),
) -> dict:
    f = load(db, principal, finding_id)
    audit.record(db, principal, "finding.viewed", f"finding:{f.finding_ref}", {})
    return finding_detail(db, f)


@router.get("/{finding_id}/explanation")
def explanation(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require("risks:read")),
    db: Session = Depends(get_db),
) -> dict:
    """Compact explanation in the Tech Spec section 12 payload shape."""
    f = load(db, principal, finding_id)
    d = finding_detail(db, f)
    return {
        "finding_id": d["finding_ref"],
        "tenant_id": d["tenant_id"],
        "tax_period": f.period_code,
        "rule": d["rule"],
        "status": f.status,
        "indicators": d["indicators"],
        "priority_score": f.priority,
        "priority_note": f.priority_note,
        "explanation": f.explanation,
        "evidence_refs": d["evidence_refs"],
        "gates": d["gates"],
        "legal_version": f.legal_version_label,
        "allowed_next_action": f.allowed_next_action,
        "label": d["label"],
    }


@router.post("/{finding_id}/review", response_model=FindingDetail)
def review(
    finding_id: uuid.UUID,
    body: ReviewRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("risks:review")),
    db: Session = Depends(get_db),
) -> dict:
    def do() -> dict:
        f = load(db, principal, finding_id)
        findings.review(db, principal, f, body.decision, body.reason, body.expected_version)
        return finding_detail(db, f)

    return run_once(db, principal, idempotency_key, f"POST /risks/{finding_id}/review", body, do)  # type: ignore[no-any-return]


@router.post("/{finding_id}/override", response_model=FindingDetail)
def override(
    finding_id: uuid.UUID,
    body: OverrideRequest,
    principal: Principal = Depends(require("risks:override")),
    db: Session = Depends(get_db),
) -> dict:
    f = load(db, principal, finding_id)
    findings.override(db, principal, f, body.likelihood, body.consequence, body.reason, body.expected_version)
    return finding_detail(db, f)


@router.post("/{finding_id}/reproduce")
def reproduce(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require("risks:read")),
    db: Session = Depends(get_db),
) -> dict:
    return evaluation.reproduce_finding(db, load(db, principal, finding_id))
