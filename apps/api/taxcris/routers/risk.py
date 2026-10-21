import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from .. import jobs
from ..config import today
from ..deps import DB, Principal, deny, require
from ..domain import risk_models, scoring
from ..models import RiskAssessment, RiskModel, RiskRun, RiskSignal, Taxpayer
from ..permissions import P
from ..schemas import (
    AssessmentDetail,
    AssessmentSummary,
    DecisionIn,
    Page,
    ReproduceOut,
    RiskModelIn,
    RiskModelOut,
    RiskRunIn,
    RiskRunOut,
    SignalOut,
)
from ._common import Limit, Offset, get_scoped, log, paginate

router = APIRouter(prefix="/v1", tags=["risk"])


@router.get("/signal-catalogue")
def signal_catalogue(_: Annotated[Principal, Depends(require(P.RISK_READ))]) -> dict:
    return {"engine_version": scoring.ENGINE_VERSION, "signals": scoring.SIGNAL_CATALOGUE,
            "default_weights": scoring.DEFAULT_WEIGHTS, "default_thresholds": scoring.DEFAULT_THRESHOLDS}


# --- model studio ------------------------------------------------------------------------------


@router.get("/risk-models", response_model=list[RiskModelOut])
def list_models(db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))]) -> list[RiskModel]:
    return list(db.execute(
        select(RiskModel).where(RiskModel.tenant_id == principal.tenant_id).order_by(RiskModel.version.desc())
    ).scalars())


@router.post("/risk-models", response_model=RiskModelOut, status_code=201)
def draft_model(body: RiskModelIn, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_MODELS_DRAFT))]) -> RiskModel:
    try:
        risk_models.validate_weights(body.weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    unknown = set(body.thresholds) - set(scoring.DEFAULT_THRESHOLDS)
    if unknown:
        raise HTTPException(422, f"Unknown thresholds: {sorted(unknown)}")
    version = (db.execute(select(func.max(RiskModel.version)).where(RiskModel.tenant_id == principal.tenant_id)).scalar_one() or 0) + 1
    m = RiskModel(tenant_id=principal.tenant_id, version=version, name=body.name, weights=body.weights,
                  thresholds={**scoring.DEFAULT_THRESHOLDS, **body.thresholds}, notes=body.notes, created_by=principal.user_id)
    db.add(m)
    db.flush()
    log(db, principal, "risk_model.drafted", "risk_model", m.id, version=version)
    db.commit()
    return m


@router.post("/risk-models/{model_id}/test", summary="Sandbox: score the current open period without persisting")
def test_model(model_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_MODELS_DRAFT))],
               tax_type: str = "PAYE", period: str | None = None, sample: int = 200) -> dict:
    """Compares this model with the approved model on the latest stored assessment inputs."""
    m = get_scoped(db, RiskModel, model_id, principal)
    current = scoring.approved_model(db, principal.tenant_id)
    q = select(RiskAssessment).where(RiskAssessment.tenant_id == principal.tenant_id, RiskAssessment.tax_type == tax_type,
                                     RiskAssessment.superseded_by_id.is_(None))
    if period:
        q = q.where(RiskAssessment.period == period)
    rows = db.execute(q.limit(min(sample, 2000))).scalars().all()
    flagged_new = flagged_cur = moved = 0
    for a in rows:
        new = scoring.evaluate(a.inputs, m.weights, m.thresholds)
        cur = scoring.evaluate(a.inputs, current.weights, current.thresholds) if current else None
        flagged_new += int(new["flagged"] and not new["suppressed"])
        if cur:
            flagged_cur += int(cur["flagged"] and not cur["suppressed"])
            moved += int(new["flagged"] != cur["flagged"])
    return {"model_version": m.version, "compared_to": current.version if current else None, "sample_size": len(rows),
            "flagged_candidate": flagged_new, "flagged_current": flagged_cur, "changed_flags": moved}


def _model_transition(model_id, db, principal, fn, *args):
    m = get_scoped(db, RiskModel, model_id, principal)
    try:
        fn(db, m, principal.user_id, principal.role, *args)
    except risk_models.FourEyesViolation as exc:
        raise deny(db, principal, "risk_model.approve", "risk_model", model_id, str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return m


@router.post("/risk-models/{model_id}/submit", response_model=RiskModelOut)
def submit_model(model_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_MODELS_DRAFT))]) -> RiskModel:
    return _model_transition(model_id, db, principal, risk_models.submit)


@router.post("/risk-models/{model_id}/approve", response_model=RiskModelOut)
def approve_model(model_id: uuid.UUID, body: DecisionIn, db: DB,
                  principal: Annotated[Principal, Depends(require(P.RISK_MODELS_APPROVE))]) -> RiskModel:
    return _model_transition(model_id, db, principal, risk_models.approve, body.reason)


@router.post("/risk-models/{model_id}/reinstate", response_model=RiskModelOut, summary="Rollback to a prior approved version")
def reinstate_model(model_id: uuid.UUID, body: DecisionIn, db: DB,
                    principal: Annotated[Principal, Depends(require(P.RISK_MODELS_APPROVE))]) -> RiskModel:
    return _model_transition(model_id, db, principal, risk_models.rollback_to, body.reason)


# --- runs ----------------------------------------------------------------------------------------


@router.post("/risk-runs", response_model=RiskRunOut, status_code=202)
def create_run(body: RiskRunIn, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_RUNS_CREATE))]) -> RiskRun:
    if body.model_version is None:
        model = scoring.approved_model(db, principal.tenant_id)
    else:
        model = db.execute(select(RiskModel).where(RiskModel.tenant_id == principal.tenant_id,
                                                   RiskModel.version == body.model_version)).scalar_one_or_none()
    if model is None or model.approved_by is None:
        raise HTTPException(409, "Risk runs require an approved model version")
    run = RiskRun(tenant_id=principal.tenant_id, model_id=model.id, model_version=model.version,
                  engine_version=scoring.ENGINE_VERSION, tax_type=body.tax_type, period=body.period,
                  as_of=body.as_of or today(), requested_by=principal.user_id)
    db.add(run)
    db.flush()
    job = jobs.enqueue(db, principal.tenant_id, "risk.run", {"run_id": str(run.id)})
    run.job_id = job.id
    log(db, principal, "risk_run.requested", "risk_run", run.id, tax_type=body.tax_type, period=body.period,
        model_version=model.version)
    db.commit()
    jobs.dispatch(job)
    db.refresh(run)
    return run


@router.get("/risk-runs", response_model=Page[RiskRunOut])
def list_runs(db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))],
              limit: int = Limit, offset: int = Offset) -> Page[RiskRunOut]:
    q = select(RiskRun).where(RiskRun.tenant_id == principal.tenant_id).order_by(RiskRun.created_at.desc())
    rows, total = paginate(db, q, limit, offset)
    return Page(items=[RiskRunOut.model_validate(r[0]) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/risk-runs/{run_id}", response_model=RiskRunOut)
def get_run(run_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))]) -> RiskRun:
    return get_scoped(db, RiskRun, run_id, principal)


# --- assessments -----------------------------------------------------------------------------------


@router.get("/risk-assessments", response_model=Page[AssessmentSummary])
def list_assessments(
    db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))],
    tax_type: str | None = None, period: str | None = None, sector: str | None = None, lga: str | None = None,
    min_confidence: float | None = None, min_score: float | None = None, suppressed: bool | None = None,
    include_superseded: bool = False, run_id: uuid.UUID | None = None, limit: int = Limit, offset: int = Offset,
) -> Page[AssessmentSummary]:
    q = (select(RiskAssessment, Taxpayer).join(Taxpayer, Taxpayer.id == RiskAssessment.taxpayer_id)
         .where(RiskAssessment.tenant_id == principal.tenant_id).order_by(RiskAssessment.score.desc()))
    if not include_superseded:
        q = q.where(RiskAssessment.superseded_by_id.is_(None))
    for col, val in ((RiskAssessment.tax_type, tax_type), (RiskAssessment.period, period), (Taxpayer.sector, sector),
                     (Taxpayer.lga, lga), (RiskAssessment.run_id, run_id), (RiskAssessment.suppressed, suppressed)):
        if val is not None:
            q = q.where(col == val)
    if min_confidence is not None:
        q = q.where(RiskAssessment.confidence >= min_confidence)
    if min_score is not None:
        q = q.where(RiskAssessment.score >= min_score)
    rows, total = paginate(db, q, limit, offset)
    items = [AssessmentSummary.model_validate(a).model_copy(update={"taxpayer_name": t.name, "lga": t.lga, "sector": t.sector})
             for a, t in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def assessment_detail(db, a: RiskAssessment) -> AssessmentDetail:
    tp = db.get(Taxpayer, a.taxpayer_id)
    signals = db.execute(select(RiskSignal).where(RiskSignal.assessment_id == a.id).order_by(RiskSignal.severity.desc())).scalars()
    return AssessmentDetail.model_validate(a).model_copy(update={
        "taxpayer_name": tp.name, "lga": tp.lga, "sector": tp.sector,
        "signals": [SignalOut.model_validate(s) for s in signals],
    })


@router.get("/risk-assessments/{assessment_id}", response_model=AssessmentDetail,
            summary="Score explanation: signals, evidence, weights and data confidence")
def get_assessment(assessment_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))]) -> AssessmentDetail:
    a = get_scoped(db, RiskAssessment, assessment_id, principal)
    log(db, principal, "assessment.view", "risk_assessment", a.id, taxpayer_id=str(a.taxpayer_id))
    db.commit()
    return assessment_detail(db, a)


@router.post("/risk-assessments/{assessment_id}/reproduce", response_model=ReproduceOut)
def reproduce(assessment_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))]) -> dict:
    a = get_scoped(db, RiskAssessment, assessment_id, principal)
    run = db.get(RiskRun, a.run_id)
    model = db.get(RiskModel, run.model_id)
    result = scoring.reproduce(a, model)
    log(db, principal, "assessment.reproduced", "risk_assessment", a.id, reproducible=result["reproducible"])
    db.commit()
    return result
