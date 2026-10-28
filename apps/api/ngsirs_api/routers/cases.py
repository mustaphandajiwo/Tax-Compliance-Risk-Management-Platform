from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError, not_found
from ..idempotency import run_once
from ..models import CaseRecord, RiskFinding
from ..schemas import (
    BatchApprove,
    CaseActionCreate,
    CaseApprove,
    CaseAssign,
    CaseClose,
    CaseCreate,
    CaseDetail,
    CaseOut,
    EvidenceVerify,
)
from ..security import crypto
from ..security.auth import Principal, declared_purpose, get_db, require
from ..serializers import case_detail, case_out, employer_names
from ..services import cases

router = APIRouter(prefix="/api/v1", tags=["intervention queue"])


def _case(db: Session, principal: Principal, case_id: uuid.UUID) -> CaseRecord:
    c = cases.get_case(db, case_id)
    if principal.lga_scope:
        f = db.get(RiskFinding, c.finding_id)
        if f is None or f.lga_code not in principal.lga_scope:
            raise not_found("Case")
    return c


@router.post("/cases", response_model=CaseDetail, status_code=201)
def create_case(
    body: CaseCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("cases:create")),
    db: Session = Depends(get_db),
) -> dict:
    def do() -> dict:
        f = db.get(RiskFinding, uuid.UUID(body.finding_id))
        if f is None or (principal.lga_scope and f.lga_code not in principal.lga_scope):
            raise not_found("Finding")
        c = cases.create(db, principal, f, body.treatment, body.rationale, body.assigned_to, body.sla_days)
        return case_detail(db, c)

    return run_once(db, principal, idempotency_key, "POST /cases", body, do)  # type: ignore[no-any-return]


@router.get("/cases", response_model=list[CaseOut])
def list_cases(
    stage: str | None = None,
    assigned_to: str | None = None,
    mine: bool = False,
    principal: Principal = Depends(require("cases:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(CaseRecord).order_by(CaseRecord.created_at.desc())
    if stage:
        q = q.where(CaseRecord.stage.in_(stage.split(",")))
    if mine:
        q = q.where(CaseRecord.assigned_to == principal.actor_id)
    elif assigned_to:
        q = q.where(CaseRecord.assigned_to == assigned_to)
    rows = list(db.execute(q.limit(500)).scalars())
    findings = (
        {
            f.id: f
            for f in db.execute(
                select(RiskFinding).where(RiskFinding.id.in_([c.finding_id for c in rows]))
            ).scalars()
        }
        if rows
        else {}
    )
    if principal.lga_scope:
        rows = [
            c
            for c in rows
            if findings.get(c.finding_id) and findings[c.finding_id].lga_code in principal.lga_scope
        ]
    names = employer_names(db, {c.employer_ref for c in rows})
    return [case_out(db, c, findings.get(c.finding_id), names) for c in rows]


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: uuid.UUID, principal: Principal = Depends(require("cases:read")), db: Session = Depends(get_db)
) -> dict:
    return case_detail(db, _case(db, principal, case_id))


@router.post("/cases/{case_id}/approve", response_model=CaseDetail)
def approve(
    case_id: uuid.UUID,
    body: CaseApprove,
    principal: Principal = Depends(require("cases:approve")),
    db: Session = Depends(get_db),
) -> dict:
    c = _case(db, principal, case_id)
    cases.approve(db, principal, c, body.note, body.expected_version)
    return case_detail(db, c)


@router.post("/cases/batch-approve")
def batch_approve(
    body: BatchApprove,
    principal: Principal = Depends(require("cases:approve")),
    db: Session = Depends(get_db),
) -> dict:
    """Approve many pending cases; ineligible ones are skipped with a reason, never forced through."""
    approved, skipped = [], []
    for cid in body.case_ids:
        try:
            c = _case(db, principal, uuid.UUID(cid))
            with db.begin_nested():
                cases.approve(db, principal, c, body.note, None)
            approved.append(
                {"case_id": cid, "case_ref": c.case_ref, "outward_permitted": c.outward_permitted}
            )
        except ApiError as exc:
            skipped.append({"case_id": cid, "reason": exc.message})
        except Exception as exc:  # noqa: BLE001 - report every case's own failure
            skipped.append({"case_id": cid, "reason": str(exc)})
    return {"approved": approved, "skipped": skipped}


@router.post("/cases/{case_id}/reject", response_model=CaseDetail)
def reject(
    case_id: uuid.UUID,
    body: CaseApprove,
    principal: Principal = Depends(require("cases:approve")),
    db: Session = Depends(get_db),
) -> dict:
    c = _case(db, principal, case_id)
    cases.reject(db, principal, c, body.note, body.expected_version)
    return case_detail(db, c)


@router.post("/cases/{case_id}/assign", response_model=CaseDetail)
def assign(
    case_id: uuid.UUID,
    body: CaseAssign,
    principal: Principal = Depends(require("cases:assign")),
    db: Session = Depends(get_db),
) -> dict:
    c = _case(db, principal, case_id)
    cases.assign(db, principal, c, body.assignee, body.expected_version)
    return case_detail(db, c)


@router.post("/cases/{case_id}/actions", response_model=CaseDetail)
def add_action(
    case_id: uuid.UUID,
    body: CaseActionCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("cases:act")),
    db: Session = Depends(get_db),
) -> dict:
    def do() -> dict:
        c = _case(db, principal, case_id)
        cases.add_action(db, principal, c, body.model_dump())
        return case_detail(db, c)

    return run_once(db, principal, idempotency_key, f"POST /cases/{case_id}/actions", body, do)  # type: ignore[no-any-return]


@router.post("/cases/{case_id}/close", response_model=CaseDetail)
def close(
    case_id: uuid.UUID,
    body: CaseClose,
    principal: Principal = Depends(require("cases:close")),
    db: Session = Depends(get_db),
) -> dict:
    c = _case(db, principal, case_id)
    cases.close(db, principal, c, body.finding_outcome, body.note, body.expected_version)
    return case_detail(db, c)


@router.post("/cases/{case_id}/evidence-packet")
def evidence_packet(
    case_id: uuid.UUID,
    purpose: str | None = Header(default=None, alias="X-Purpose"),
    principal: Principal = Depends(require("evidence:export")),
    db: Session = Depends(get_db),
) -> dict:
    p = declared_purpose(principal, purpose)
    c = _case(db, principal, case_id)
    if c.stage in ("pending_approval", "rejected"):
        raise ApiError(409, "conflict", "Evidence packets are exported only for approved desk-review cases")
    return cases.evidence_packet(db, principal, c, p or "")


@router.post("/evidence-packets/verify")
def verify_packet(body: EvidenceVerify, _: Principal = Depends(require("cases:read"))) -> dict:
    from risk_engine.hashing import canonical_json, sha256_hex

    data = canonical_json(body.packet).encode()
    return {
        "valid": crypto.verify_signature(data, body.signature),
        "sha256": sha256_hex(data),
        "key_id": crypto.signing_key_id(),
    }
