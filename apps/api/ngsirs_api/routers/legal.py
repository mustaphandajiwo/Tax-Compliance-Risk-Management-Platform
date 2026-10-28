from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import not_found
from ..models import LegalInstrument, LegalRuleVersion, TaxObligation
from ..schemas import ApprovalNote, LegalVersionDraft
from ..security.auth import Principal, get_db, require
from ..services import legal

router = APIRouter(prefix="/api/v1/legal", tags=["legal obligations"])


def version_payload(v: LegalRuleVersion, instruments: dict) -> dict:
    inst = instruments.get(v.instrument_id)
    return {
        "id": str(v.id),
        "code": v.code,
        "version": v.version,
        "tax_type": v.tax_type,
        "obligation_type": v.obligation_type,
        "instrument": inst.code if inst else None,
        "instrument_title": inst.title if inst else None,
        "authority": inst.authority if inst else None,
        "provision_ref": v.provision_ref,
        "jurisdiction": v.jurisdiction,
        "effective_from": v.effective_from.isoformat(),
        "effective_to": v.effective_to.isoformat() if v.effective_to else None,
        "parameters": v.parameters,
        "status": v.status,
        "drafted_by": v.drafted_by,
        "approved_by": v.approved_by,
        "approved_at": v.approved_at.isoformat() if v.approved_at else None,
        "approval_note": v.approval_note,
        "content_hash": v.content_hash,
        "is_synthetic": v.is_synthetic,
    }


@router.get("/instruments")
def instruments(_: Principal = Depends(require("legal:read")), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": str(i.id),
            "code": i.code,
            "title": i.title,
            "authority": i.authority,
            "jurisdiction": i.jurisdiction,
            "status": i.status,
            "source_note": i.source_note,
            "is_synthetic": i.is_synthetic,
        }
        for i in db.execute(select(LegalInstrument)).scalars()
    ]


@router.get("/obligations")
def obligations(
    code: str | None = None, _: Principal = Depends(require("legal:read")), db: Session = Depends(get_db)
) -> dict:
    insts = {i.id: i for i in db.execute(select(LegalInstrument)).scalars()}
    q = select(LegalRuleVersion).order_by(LegalRuleVersion.code, LegalRuleVersion.effective_from)
    if code:
        q = q.where(LegalRuleVersion.code == code)
    versions = [version_payload(v, insts) for v in db.execute(q).scalars()]
    counts: dict[str, int] = {}
    for o in db.execute(select(TaxObligation).where(TaxObligation.is_current)).scalars():
        counts[o.status] = counts.get(o.status, 0) + 1
    return {
        "codes": legal.OBLIGATION_CODES,
        "versions": versions,
        "taxpayer_obligations_by_status": counts,
        "notice": "All parameters are SYNTHETIC placeholders pending NGSIRS legal confirmation from "
        "authenticated texts. No rate or deadline is taken from internet sources.",
    }


@router.get("/resolve")
def resolve(
    code: str,
    period: str = Query(pattern=r"^\d{4}-\d{2}$"),
    _: Principal = Depends(require("legal:read")),
    db: Session = Depends(get_db),
) -> dict:
    v = legal.resolve(db, code, period)
    any_v = legal.resolve(db, code, period, approved_only=False)
    insts = {i.id: i for i in db.execute(select(LegalInstrument)).scalars()}
    due = (
        legal.due_date_for(period, v.parameters).isoformat()
        if v and "due_day_of_following_month" in v.parameters
        else None
    )
    return {
        "code": code,
        "period": period,
        "approved_version": version_payload(v, insts) if v else None,
        "unapproved_candidate": version_payload(any_v, insts) if any_v and not v else None,
        "due_at": due,
        "status": "resolved" if v else "obligation_unverified",
    }


@router.post("/versions", status_code=201)
def draft_version(
    body: LegalVersionDraft,
    principal: Principal = Depends(require("legal:draft")),
    db: Session = Depends(get_db),
) -> dict:
    v = legal.draft_version(db, principal, body.model_dump())
    insts = {i.id: i for i in db.execute(select(LegalInstrument)).scalars()}
    return version_payload(v, insts)


@router.post("/versions/{version_id}/approve")
def approve_version(
    version_id: uuid.UUID,
    body: ApprovalNote,
    principal: Principal = Depends(require("legal:approve")),
    db: Session = Depends(get_db),
) -> dict:
    v = legal.approve_version(db, principal, version_id, body.note)
    insts = {i.id: i for i in db.execute(select(LegalInstrument)).scalars()}
    return version_payload(v, insts)


@router.get("/versions/{version_id}")
def get_version(
    version_id: uuid.UUID, _: Principal = Depends(require("legal:read")), db: Session = Depends(get_db)
) -> dict:
    v = db.get(LegalRuleVersion, version_id)
    if v is None:
        raise not_found("Legal version")
    insts = {i.id: i for i in db.execute(select(LegalInstrument)).scalars()}
    return version_payload(v, insts)
