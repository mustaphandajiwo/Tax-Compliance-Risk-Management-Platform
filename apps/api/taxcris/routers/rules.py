import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..deps import DB, Principal, deny, require
from ..domain import obligations as engine
from ..models import LegalRule
from ..permissions import P
from ..schemas import DecisionIn, LegalRuleIn, LegalRuleOut, RuleTestIn
from ._common import get_scoped, log

router = APIRouter(prefix="/v1/legal-rules", tags=["legal catalogue"])


@router.get("", response_model=list[LegalRuleOut])
def list_rules(db: DB, principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_READ))],
               tax_type: str | None = None, status: str | None = None) -> list[LegalRule]:
    q = select(LegalRule).where(LegalRule.tenant_id == principal.tenant_id).order_by(LegalRule.rule_code, LegalRule.version.desc())
    if tax_type:
        q = q.where(LegalRule.tax_type == tax_type)
    if status:
        q = q.where(LegalRule.status == status)
    return list(db.execute(q).scalars())


@router.post("", response_model=LegalRuleOut, status_code=201, summary="Draft a new rule version")
def draft_rule(body: LegalRuleIn, db: DB, principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_DRAFT))]) -> LegalRule:
    try:
        engine.compute_due_date(body.deadline, engine.period_bounds("2024-01")[1])
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, f"Invalid deadline specification: {exc}")
    if body.valid_to and body.valid_to < body.valid_from:
        raise HTTPException(422, "valid_to precedes valid_from")
    version = (db.execute(
        select(func.max(LegalRule.version)).where(LegalRule.tenant_id == principal.tenant_id, LegalRule.rule_code == body.rule_code)
    ).scalar_one() or 0) + 1
    rule = LegalRule(tenant_id=principal.tenant_id, version=version, created_by=principal.user_id, **body.model_dump())
    db.add(rule)
    db.flush()
    log(db, principal, "legal_rule.drafted", "legal_rule", rule.id, rule_code=rule.rule_code, version=version)
    db.commit()
    return rule


def _transition(rule_id, db, principal, fn, *args):
    rule = get_scoped(db, LegalRule, rule_id, principal)
    try:
        fn(db, rule, principal.user_id, principal.role, *args)
    except engine.FourEyesViolation as exc:
        raise deny(db, principal, "legal_rule.approve", "legal_rule", rule_id, str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return rule


@router.post("/{rule_id}/submit", response_model=LegalRuleOut)
def submit(rule_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_DRAFT))]) -> LegalRule:
    return _transition(rule_id, db, principal, engine.submit_rule)


@router.post("/{rule_id}/approve", response_model=LegalRuleOut, summary="Second-person approval")
def approve(rule_id: uuid.UUID, body: DecisionIn, db: DB,
            principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_APPROVE))]) -> LegalRule:
    return _transition(rule_id, db, principal, engine.approve_rule, body.reason)


@router.post("/{rule_id}/retire", response_model=LegalRuleOut, summary="Rollback: retire a version")
def retire(rule_id: uuid.UUID, body: DecisionIn, db: DB,
           principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_APPROVE))]) -> LegalRule:
    return _transition(rule_id, db, principal, engine.retire_rule, body.reason)


@router.post("/{rule_id}/test", summary="Sandbox: preview the deadline this version produces for a period")
def test_rule(rule_id: uuid.UUID, body: RuleTestIn, db: DB,
              principal: Annotated[Principal, Depends(require(P.LEGAL_RULES_READ))]) -> dict:
    rule = get_scoped(db, LegalRule, rule_id, principal)
    periods = engine.periods_for(rule.frequency, body.period)
    out = []
    approved = engine.approved_rules(db, principal.tenant_id)
    for p in periods:
        start, end = engine.period_bounds(p)
        in_force = engine.select_rule(approved, rule.tax_type, start)
        out.append({
            "period": p, "due_date": engine.compute_due_date(rule.deadline, end).isoformat(),
            "this_version_valid": rule.valid_from <= start and (rule.valid_to is None or start <= rule.valid_to),
            "version_in_force": in_force.version if in_force else None,
        })
    return {"rule_code": rule.rule_code, "version": rule.version, "results": out}
