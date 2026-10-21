import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..config import today
from ..deps import DB, Principal, deny, require
from ..domain import cases as workflow
from ..models import Alert, Case, CaseAction, Intervention, RiskAssessment, Taxpayer, User
from ..permissions import P
from ..schemas import (
    AlertOut,
    CaseActionIn,
    CaseActionOut,
    CaseCreate,
    CaseDetail,
    CaseSummary,
    InterventionOut,
    Page,
    TriageIn,
)
from ._common import Limit, Offset, get_scoped, paginate
from .risk import assessment_detail

router = APIRouter(prefix="/v1", tags=["alerts & cases"])


def _alert_out(a: Alert, t: Taxpayer, ra: RiskAssessment) -> AlertOut:
    return AlertOut.model_validate(a).model_copy(update={
        "taxpayer_name": t.name, "lga": t.lga, "sector": t.sector, "confidence": ra.confidence,
        "exposure_estimate": ra.exposure_estimate, "reason_codes": ra.reason_codes,
    })


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))],
    status: str | None = None, tax_type: str | None = None, period: str | None = None, lga: str | None = None,
    sector: str | None = None, reason_code: str | None = None, min_confidence: float | None = None,
    limit: int = Limit, offset: int = Offset,
) -> Page[AlertOut]:
    q = (select(Alert, Taxpayer, RiskAssessment).join(Taxpayer, Taxpayer.id == Alert.taxpayer_id)
         .join(RiskAssessment, RiskAssessment.id == Alert.assessment_id)
         .where(Alert.tenant_id == principal.tenant_id).order_by(Alert.priority.desc(), Alert.created_at))
    for col, val in ((Alert.status, status), (Alert.tax_type, tax_type), (Alert.period, period), (Taxpayer.lga, lga),
                     (Taxpayer.sector, sector)):
        if val:
            q = q.where(col == val)
    if min_confidence is not None:
        q = q.where(RiskAssessment.confidence >= min_confidence)
    if reason_code:
        # Portable JSON-array containment: filter in Python after narrowing.
        rows = [r for r in db.execute(q).all() if reason_code in (r[2].reason_codes or [])]
        total = len(rows)
        rows = rows[offset: offset + limit]
    else:
        rows, total = paginate(db, q, limit, offset)
    return Page(items=[_alert_out(a, t, ra) for a, t, ra in rows], total=total, limit=limit, offset=offset)


@router.get("/alerts/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.RISK_READ))]) -> AlertOut:
    a = get_scoped(db, Alert, alert_id, principal)
    return _alert_out(a, db.get(Taxpayer, a.taxpayer_id), db.get(RiskAssessment, a.assessment_id))


@router.post("/alerts/{alert_id}/triage", response_model=AlertOut, summary="Confirm, dismiss or escalate with reason")
def triage_alert(alert_id: uuid.UUID, body: TriageIn, db: DB,
                 principal: Annotated[Principal, Depends(require(P.ALERTS_TRIAGE))]) -> AlertOut:
    a = get_scoped(db, Alert, alert_id, principal)
    try:
        workflow.triage(db, a, body.decision, body.reason, principal.user_id, principal.role)
    except workflow.WorkflowError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return _alert_out(a, db.get(Taxpayer, a.taxpayer_id), db.get(RiskAssessment, a.assessment_id))


# --- cases ------------------------------------------------------------------------------------------


def _summary(c: Case, name: str | None) -> CaseSummary:
    return CaseSummary.model_validate(c).model_copy(update={"taxpayer_name": name})


def _detail(db, c: Case, principal: Principal) -> CaseDetail:
    tp = db.get(Taxpayer, c.taxpayer_id)
    alert = db.get(Alert, c.alert_id)
    names = dict(db.execute(select(User.id, User.full_name).where(User.tenant_id == c.tenant_id)).all())
    actions = db.execute(select(CaseAction).where(CaseAction.case_id == c.id).order_by(CaseAction.created_at)).scalars()
    ivs = db.execute(select(Intervention).where(Intervention.case_id == c.id).order_by(Intervention.created_at)).scalars()
    return CaseDetail(
        **_summary(c, tp.name).model_dump(), alert_id=c.alert_id, owner_id=c.owner_id, outcome=c.outcome,
        amount_collected=c.amount_collected, closed_at=c.closed_at,
        sla_breached=(c.closed_at.date() if c.closed_at else today()) > c.sla_due,
        available_actions=workflow.available_actions(c, principal.permissions),
        actions=[CaseActionOut.model_validate(a).model_copy(update={"actor_name": names.get(a.actor_id)}) for a in actions],
        interventions=[InterventionOut.model_validate(i) for i in ivs],
        assessment=assessment_detail(db, db.get(RiskAssessment, alert.assessment_id)),
    )


@router.post("/cases", response_model=CaseDetail, status_code=201, summary="Open a case from a reviewed alert")
def create_case(body: CaseCreate, db: DB, principal: Annotated[Principal, Depends(require(P.CASES_CREATE))]) -> CaseDetail:
    alert = get_scoped(db, Alert, body.alert_id, principal)
    try:
        case = workflow.create_case(db, alert, principal.user_id, principal.role, body.justification)
    except workflow.DuplicateCase as exc:
        db.rollback()
        raise HTTPException(409, f"An open case already exists for this taxpayer or alert: {exc.case.reference}")
    except workflow.WorkflowError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return _detail(db, case, principal)


@router.get("/cases", response_model=Page[CaseSummary])
def list_cases(db: DB, principal: Annotated[Principal, Depends(require(P.CASES_READ))],
               status: str | None = None, assignee: str | None = None, sla_breached: bool | None = None,
               limit: int = Limit, offset: int = Offset) -> Page[CaseSummary]:
    q = (select(Case, Taxpayer.name).join(Taxpayer, Taxpayer.id == Case.taxpayer_id)
         .where(Case.tenant_id == principal.tenant_id).order_by(Case.sla_due))
    if status:
        q = q.where(Case.status == status)
    if assignee == "me":
        q = q.where(Case.assignee_id == principal.user_id)
    elif assignee:
        q = q.where(Case.assignee_id == uuid.UUID(assignee))
    if sla_breached is not None:
        q = q.where(Case.status != "closed")
        q = q.where(Case.sla_due < today()) if sla_breached else q.where(Case.sla_due >= today())
    rows, total = paginate(db, q, limit, offset)
    return Page(items=[_summary(c, n) for c, n in rows], total=total, limit=limit, offset=offset)


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.CASES_READ))]) -> CaseDetail:
    return _detail(db, get_scoped(db, Case, case_id, principal), principal)


@router.post("/cases/{case_id}/actions", response_model=CaseDetail, summary="Workflow transition with justification")
def case_action(case_id: uuid.UUID, body: CaseActionIn, db: DB,
                principal: Annotated[Principal, Depends(require(P.CASES_READ))]) -> CaseDetail:
    case = get_scoped(db, Case, case_id, principal)
    try:
        workflow.apply_action(db, case, body.action, user_id=principal.user_id, role=principal.role,
                              perms=principal.permissions, justification=body.justification, payload=body.payload)
    except workflow.PermissionDenied as exc:
        raise deny(db, principal, f"case.{body.action}", "case", case_id, str(exc))
    except workflow.WorkflowError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    db.commit()
    return _detail(db, case, principal)
