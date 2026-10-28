from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.facts import FACT_SCHEMA, HISTORY_FIELDS, HISTORY_SERIES
from risk_engine.predicates import ELIGIBILITY, EXCLUSIONS, HOLDS
from risk_engine.treatment import TREATMENTS

from ..errors import not_found
from ..idempotency import run_once
from ..models import EvaluationRun, RuleDefinitionRow, RuleVersion
from ..schemas import (
    BacktestRequest,
    EvaluationRequest,
    EvaluationRunOut,
    ReasonRequest,
    RuleApproval,
    RuleDraft,
    RuleValidateRequest,
)
from ..security.auth import Principal, get_db, require
from ..serializers import run_out
from ..services import evaluation, rules

router = APIRouter(prefix="/api/v1/rules", tags=["rules & evaluations"])


# --- evaluations (declared first so /evaluations is not taken as a rule code) ---------


@router.post("/evaluations", response_model=EvaluationRunOut, status_code=201)
def run_evaluation(
    body: EvaluationRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("evaluations:run_operational")),
    db: Session = Depends(get_db),
) -> dict:
    def do() -> dict:
        run, created = evaluation.run_evaluation(
            db,
            principal,
            principal.tenant_id,
            as_of=body.as_of,
            period_from=body.period_from,
            period_to=body.period_to,
            idempotency_key=idempotency_key,
        )
        return {**run_out(db, run), "reused": not created}

    return run_once(db, principal, idempotency_key, "POST /rules/evaluations", body, do)  # type: ignore[no-any-return]


@router.get("/evaluations", response_model=list[EvaluationRunOut])
def list_runs(
    _: Principal = Depends(require("evaluations:read")), db: Session = Depends(get_db)
) -> list[dict]:
    runs = db.execute(select(EvaluationRun).order_by(EvaluationRun.started_at.desc()).limit(100)).scalars()
    return [run_out(db, r) for r in runs]


@router.get("/evaluations/{run_id}", response_model=EvaluationRunOut)
def get_run(
    run_id: uuid.UUID, _: Principal = Depends(require("evaluations:read")), db: Session = Depends(get_db)
) -> dict:
    r = db.get(EvaluationRun, run_id)
    if r is None:
        raise not_found("Evaluation run")
    return run_out(db, r)


@router.post("/evaluations/{run_id}/reproduce")
def reproduce_run(
    run_id: uuid.UUID, _: Principal = Depends(require("evaluations:read")), db: Session = Depends(get_db)
) -> dict:
    r = db.get(EvaluationRun, run_id)
    if r is None:
        raise not_found("Evaluation run")
    return evaluation.reproduce_run(db, r)


# --- rule language reference ----------------------------------------------------------


@router.get("/language")
def language(_: Principal = Depends(require("rules:read"))) -> dict:
    return {
        "fact_kinds": FACT_SCHEMA,
        "history_series": HISTORY_SERIES,
        "history_fields": HISTORY_FIELDS,
        "operators": ["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null"],
        "combinators": ["all", "any", "not", "aggregate(count)"],
        "eligibility": {k: {"description": p.description, "kinds": p.kinds} for k, p in ELIGIBILITY.items()},
        "exclusions": {k: {"description": p.description, "kinds": p.kinds} for k, p in EXCLUSIONS.items()},
        "holds": {k: {"description": p.description, "kinds": p.kinds} for k, p in HOLDS.items()},
        "treatments": {
            k: {"label": t.label, "human_gate": t.human_gate, "outward": t.outward}
            for k, t in TREATMENTS.items()
        },
    }


@router.post("/validate")
def validate(body: RuleValidateRequest, _: Principal = Depends(require("rules:read"))) -> dict:
    return rules.validation_report(body.definition)


# --- registry ----------------------------------------------------------------------------


@router.get("")
def list_rules(_: Principal = Depends(require("rules:read")), db: Session = Depends(get_db)) -> list[dict]:
    versions: dict[str, list[RuleVersion]] = {}
    for v in db.execute(select(RuleVersion).order_by(RuleVersion.created_at)).scalars():
        versions.setdefault(v.rule_code, []).append(v)
    out = []
    for d in db.execute(select(RuleDefinitionRow).order_by(RuleDefinitionRow.rule_code)).scalars():
        vs = versions.get(d.rule_code, [])
        active = next((v for v in vs if v.id == d.active_version_id), None)
        out.append(
            {
                "rule_code": d.rule_code,
                "domain": d.domain,
                "title": d.title,
                "description": d.description,
                "catalogue_status": d.catalogue_status,
                "legacy_codes": d.legacy_codes,
                "default_treatment": d.default_treatment,
                "active_version": active.version if active else None,
                "active_since": active.activated_at.isoformat() if active and active.activated_at else None,
                "versions": [{"id": str(v.id), "version": v.version, "status": v.status} for v in vs],
            }
        )
    return out


@router.get("/{rule_code}")
def get_rule(
    rule_code: str, _: Principal = Depends(require("rules:read")), db: Session = Depends(get_db)
) -> dict:
    d = db.execute(
        select(RuleDefinitionRow).where(RuleDefinitionRow.rule_code == rule_code)
    ).scalar_one_or_none()
    if d is None:
        raise not_found("Rule")
    vs = list(
        db.execute(
            select(RuleVersion).where(RuleVersion.rule_code == rule_code).order_by(RuleVersion.created_at)
        ).scalars()
    )
    return {
        "rule_code": d.rule_code,
        "domain": d.domain,
        "title": d.title,
        "description": d.description,
        "catalogue_status": d.catalogue_status,
        "legacy_codes": d.legacy_codes,
        "active_version_id": str(d.active_version_id) if d.active_version_id else None,
        "versions": [rules.version_payload(v) for v in vs],
    }


@router.get("/{rule_code}/diff")
def diff(
    rule_code: str,
    from_version: str,
    to_version: str,
    _: Principal = Depends(require("rules:read")),
    db: Session = Depends(get_db),
) -> dict:
    vs = {
        v.version: v
        for v in db.execute(select(RuleVersion).where(RuleVersion.rule_code == rule_code)).scalars()
    }
    if from_version not in vs or to_version not in vs:
        raise not_found("Rule version")
    return {
        "rule_code": rule_code,
        "from": from_version,
        "to": to_version,
        "changes": rules.diff(vs[from_version].expression_json, vs[to_version].expression_json),
    }


@router.post("", status_code=201)
def draft(
    body: RuleDraft, principal: Principal = Depends(require("rules:draft")), db: Session = Depends(get_db)
) -> dict:
    return rules.version_payload(rules.draft(db, principal, body.definition, body.change_note))


@router.post("/versions/{version_id}/backtest")
def backtest(
    version_id: uuid.UUID,
    body: BacktestRequest,
    principal: Principal = Depends(require("rules:backtest")),
    db: Session = Depends(get_db),
) -> dict:
    rv = rules.get_version(db, version_id)
    return evaluation.backtest(
        db, principal, rv, as_of=body.as_of, period_from=body.period_from, period_to=body.period_to
    )


@router.post("/versions/{version_id}/submit")
def submit(
    version_id: uuid.UUID,
    principal: Principal = Depends(require("rules:draft")),
    db: Session = Depends(get_db),
) -> dict:
    return rules.version_payload(rules.submit(db, principal, rules.get_version(db, version_id)))


@router.post("/versions/{version_id}/approve")
def approve(
    version_id: uuid.UUID,
    body: RuleApproval,
    principal: Principal = Depends(require("rules:approve")),
    db: Session = Depends(get_db),
) -> dict:
    return rules.version_payload(
        rules.approve(db, principal, rules.get_version(db, version_id), body.note, body.as_role)
    )


@router.post("/versions/{version_id}/reject")
def reject(
    version_id: uuid.UUID,
    body: ReasonRequest,
    principal: Principal = Depends(require("rules:approve")),
    db: Session = Depends(get_db),
) -> dict:
    return rules.version_payload(rules.reject(db, principal, rules.get_version(db, version_id), body.reason))


@router.post("/versions/{version_id}/activate")
def activate(
    version_id: uuid.UUID,
    body: ReasonRequest,
    principal: Principal = Depends(require("rules:activate")),
    db: Session = Depends(get_db),
) -> dict:
    return rules.version_payload(
        rules.activate(db, principal, rules.get_version(db, version_id), body.reason)
    )


@router.post("/{rule_code}/rollback")
def rollback(
    rule_code: str,
    body: ReasonRequest,
    principal: Principal = Depends(require("rules:activate")),
    db: Session = Depends(get_db),
) -> dict:
    return rules.version_payload(rules.rollback(db, principal, rule_code, body.reason))
