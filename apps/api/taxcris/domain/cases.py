"""Alert triage, case workflow and intervention policy (FR-06, FR-07, PRD §7).

Every transition is permission-checked, requires a justification and emits an audit event.
Consequential steps need a second person: proposals are approved by someone other than the
proposer, and audit referrals are decided by an audit manager other than the referrer.
The system never issues legal notices or sanctions itself.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import today
from ..models import Alert, Case, CaseAction, Intervention, RiskAssessment, Tenant, User
from ..permissions import P, Role

INTERVENTIONS = (
    "no_action",
    "correct_data",
    "educational_communication",
    "filing_reminder",
    "assisted_filing",
    "desk_verification",
    "payment_follow_up",
    "audit_referral",
    "investigation_referral",
)
REFERRALS = {"audit_referral", "investigation_referral"}
LOW_CONFIDENCE_ALLOWED = {"no_action", "correct_data"}
DISPOSITIONS = ("resolved_compliant", "resolved_collected", "data_corrected", "no_further_action", "referred_external", "audit_completed")
DEFAULT_SLA_DAYS = {
    "default": 30,
    "no_action": 7,
    "correct_data": 14,
    "educational_communication": 21,
    "filing_reminder": 21,
    "assisted_filing": 30,
    "desk_verification": 45,
    "payment_follow_up": 30,
    "audit_referral": 90,
    "investigation_referral": 120,
}


class WorkflowError(Exception):
    """Invalid transition or payload (HTTP 409/422)."""


class PermissionDenied(Exception):
    """Actor lacks authority for this specific step (HTTP 403)."""


@dataclass(frozen=True)
class Transition:
    sources: tuple[str, ...]
    target: str | None  # None = stay in current status
    permission: P


TRANSITIONS: dict[str, Transition] = {
    "submit_proposal": Transition(("open",), "pending_approval", P.CASES_PROPOSE),
    "approve_proposal": Transition(("pending_approval",), "approved", P.CASES_APPROVE),
    "return_for_revision": Transition(("pending_approval",), "open", P.CASES_APPROVE),
    "start_work": Transition(("approved",), "in_progress", P.CASES_WORK),
    "record_contact": Transition(("in_progress",), None, P.CASES_WORK),
    "refer_audit": Transition(("open", "in_progress", "approved"), "audit_referral_pending", P.CASES_APPROVE),
    "approve_audit": Transition(("audit_referral_pending",), "audit_in_progress", P.AUDITS_DECIDE),
    "reject_audit": Transition(("audit_referral_pending",), "open", P.AUDITS_DECIDE),
    "record_audit_findings": Transition(("audit_in_progress",), None, P.AUDITS_DECIDE),
    "reassign": Transition(("open", "pending_approval", "approved", "in_progress"), None, P.CASES_APPROVE),
    "close": Transition(("open", "approved", "in_progress", "audit_in_progress"), "closed", P.CASES_APPROVE),
}


def available_actions(db: Session, case: Case, perms: frozenset[P], user_id: uuid.UUID) -> list[str]:
    """Actions this actor can actually take now, including four-eyes and assignee rules."""
    iv = _latest_intervention(db, case)
    out = []
    for name, t in TRANSITIONS.items():
        if case.status not in t.sources or t.permission not in perms:
            continue
        if name in ("approve_proposal", "return_for_revision", "approve_audit", "reject_audit") and iv is not None \
                and iv.proposed_by == user_id:
            continue
        if name == "start_work" and case.assignee_id not in (None, user_id):
            continue
        if name == "record_contact" and case.assignee_id != user_id:
            continue
        out.append(name)
    return out


def sla_days(tenant: Tenant, intervention: str | None) -> int:
    table = {**DEFAULT_SLA_DAYS, **(tenant.config or {}).get("sla_days", {})}
    return int(table.get(intervention or "default", table["default"]))


# ---------------------------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------------------------


def triage(db: Session, alert: Alert, decision: str, reason: str, user_id: uuid.UUID, role: str) -> Alert:
    if decision not in ("confirm", "dismiss", "escalate"):
        raise WorkflowError("decision must be confirm, dismiss or escalate")
    if len(reason.strip()) < 5:
        raise WorkflowError("A reason of at least 5 characters is required")
    if alert.status not in ("open", "data_verification", "escalated"):
        raise WorkflowError(f"Alert already triaged ({alert.status})")
    if decision == "confirm" and alert.status == "data_verification":
        raise WorkflowError("Low-confidence alerts must be resolved through data verification before confirmation")
    before = {"status": alert.status}
    alert.status = {"confirm": "confirmed", "dismiss": "dismissed", "escalate": "escalated"}[decision]
    alert.triaged_by, alert.triage_reason, alert.triaged_at = user_id, reason, datetime.now(timezone.utc)
    audit.record(db, tenant_id=alert.tenant_id, actor_id=user_id, actor_role=role, action=f"alert.{alert.status}",
                 resource_type="alert", resource_id=alert.id, details={"reason": reason},
                 before=before, after={"status": alert.status})
    return alert


# ---------------------------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------------------------


class DuplicateCase(Exception):
    def __init__(self, case: Case):
        super().__init__(case.reference)
        self.case = case


def create_case(db: Session, alert: Alert, user_id: uuid.UUID, role: str, justification: str) -> Case:
    if alert.status not in ("confirmed", "escalated"):
        raise WorkflowError("Cases can only be opened from a confirmed or escalated alert")
    if len(justification.strip()) < 5:
        raise WorkflowError("A justification of at least 5 characters is required")
    dup = db.execute(
        select(Case).where(
            Case.tenant_id == alert.tenant_id,
            (Case.alert_id == alert.id) | ((Case.taxpayer_id == alert.taxpayer_id) & (Case.status != "closed")),
        )
    ).scalars().first()
    if dup is not None:
        raise DuplicateCase(dup)
    tenant = db.get(Tenant, alert.tenant_id)
    year = today().year
    n = db.execute(select(func.count(Case.id)).where(Case.tenant_id == tenant.id)).scalar_one() + 1
    case = Case(
        tenant_id=tenant.id, reference=f"{tenant.state_code}-{year}-{n:05d}", taxpayer_id=alert.taxpayer_id,
        alert_id=alert.id, status="open", owner_id=user_id, created_by=user_id,
        sla_due=today() + timedelta(days=sla_days(tenant, None)),
    )
    db.add(case)
    db.flush()
    db.add(CaseAction(tenant_id=tenant.id, case_id=case.id, action="create", from_status="-", to_status="open",
                      actor_id=user_id, justification=justification, payload={"alert_id": str(alert.id)}))
    audit.record(db, tenant_id=tenant.id, actor_id=user_id, actor_role=role, action="case.created", resource_type="case",
                 resource_id=case.id, details={"reference": case.reference, "alert_id": str(alert.id), "justification": justification})
    return case


def _latest_intervention(db: Session, case: Case) -> Intervention | None:
    return db.execute(
        select(Intervention).where(Intervention.case_id == case.id).order_by(Intervention.created_at.desc())
    ).scalars().first()


def _assessment(db: Session, case: Case) -> RiskAssessment:
    alert = db.get(Alert, case.alert_id)
    return db.get(RiskAssessment, alert.assessment_id)


def apply_action(
    db: Session, case: Case, action: str, *, user_id: uuid.UUID, role: str, perms: frozenset[P],
    justification: str, payload: dict,
) -> Case:
    t = TRANSITIONS.get(action)
    if t is None:
        raise WorkflowError(f"Unknown action '{action}'")
    if t.permission not in perms:
        raise PermissionDenied(f"Role '{role}' may not perform '{action}'")
    if case.status not in t.sources:
        raise WorkflowError(f"Action '{action}' is not allowed from status '{case.status}'")
    if len((justification or "").strip()) < 5:
        raise WorkflowError("A justification of at least 5 characters is required")

    tenant = db.get(Tenant, case.tenant_id)
    from_status = case.status
    target = t.target or case.status
    now = datetime.now(timezone.utc)

    if action == "submit_proposal":
        itype = payload.get("intervention_type")
        if itype not in INTERVENTIONS:
            raise WorkflowError(f"intervention_type must be one of {', '.join(INTERVENTIONS)}")
        if itype in REFERRALS:
            raise WorkflowError("Audit and investigation referrals are raised by a compliance manager via 'refer_audit'")
        alert = db.get(Alert, case.alert_id)
        assessment = _assessment(db, case)
        if (alert.status == "data_verification" or assessment.suppressed) and itype not in LOW_CONFIDENCE_ALLOWED:
            raise WorkflowError("Data confidence is insufficient; only 'correct_data' or 'no_action' may be proposed")
        db.add(Intervention(tenant_id=case.tenant_id, case_id=case.id, type=itype, rationale=justification, proposed_by=user_id))
        case.proposed_intervention = itype

    elif action in ("approve_proposal", "return_for_revision"):
        iv = _latest_intervention(db, case)
        if iv is None or iv.status != "proposed":
            raise WorkflowError("No pending intervention proposal")
        if iv.proposed_by == user_id:
            raise PermissionDenied("A proposal must be approved by someone other than its proposer")
        if action == "approve_proposal":
            assignee = payload.get("assignee_id")
            if assignee:
                _assign(db, case, assignee)
            iv.status, iv.approved_by, iv.approved_at = "approved", user_id, now
            case.sla_due = today() + timedelta(days=sla_days(tenant, iv.type))
        else:
            iv.status = "returned"

    elif action == "start_work":
        if case.assignee_id is not None and case.assignee_id != user_id:
            raise PermissionDenied("Only the assigned officer can start work on this case")
        if case.assignee_id is None:
            case.assignee_id = user_id
        iv = _latest_intervention(db, case)
        if iv is not None and iv.status == "approved":
            iv.status, iv.execution_time = "executed", now

    elif action == "record_contact":
        if case.assignee_id != user_id:
            raise PermissionDenied("Only the assigned officer can record contact")
        if payload.get("channel") not in ("letter", "email", "sms", "phone", "visit", "portal"):
            raise WorkflowError("channel must be one of letter, email, sms, phone, visit, portal")

    elif action == "refer_audit":
        itype = payload.get("intervention_type", "audit_referral")
        if itype not in REFERRALS:
            raise WorkflowError("intervention_type must be audit_referral or investigation_referral")
        assessment = _assessment(db, case)
        if assessment.suppressed:
            raise WorkflowError("Cannot refer for audit while data confidence is insufficient")
        if not payload.get("materiality"):
            raise WorkflowError("A materiality statement is required for audit referral")
        db.add(Intervention(tenant_id=case.tenant_id, case_id=case.id, type=itype, rationale=justification, proposed_by=user_id))
        case.proposed_intervention = itype

    elif action in ("approve_audit", "reject_audit"):
        iv = _latest_intervention(db, case)
        if iv is None or iv.type not in REFERRALS or iv.status != "proposed":
            raise WorkflowError("No pending audit referral")
        if iv.proposed_by == user_id:
            raise PermissionDenied("The referring manager cannot decide their own audit referral")
        if action == "approve_audit":
            iv.status, iv.approved_by, iv.approved_at, iv.execution_time = "approved", user_id, now, now
            if payload.get("assignee_id"):
                _assign(db, case, payload["assignee_id"], allowed_roles=(Role.AUDIT_MANAGER, Role.COMPLIANCE_OFFICER))
            case.sla_due = today() + timedelta(days=sla_days(tenant, iv.type))
        else:
            iv.status = "rejected"
            case.proposed_intervention = None

    elif action == "record_audit_findings":
        if not payload.get("findings"):
            raise WorkflowError("findings are required")
        iv = _latest_intervention(db, case)
        if iv is not None:
            iv.outcome = str(payload["findings"])

    elif action == "reassign":
        if not payload.get("assignee_id"):
            raise WorkflowError("assignee_id is required")
        _assign(db, case, payload["assignee_id"])

    elif action == "close":
        disp = payload.get("disposition")
        if disp not in DISPOSITIONS:
            raise WorkflowError(f"disposition must be one of {', '.join(DISPOSITIONS)}")
        case.disposition, case.outcome = disp, payload.get("outcome") or justification
        if payload.get("amount_collected") is not None:
            amt = Decimal(str(payload["amount_collected"]))
            if amt < 0:
                raise WorkflowError("amount_collected cannot be negative")
            case.amount_collected = amt
        case.closed_at = now
        iv = _latest_intervention(db, case)
        if iv is not None and iv.outcome is None and iv.status in ("approved", "executed"):
            iv.outcome = case.outcome

    case.status = target
    db.add(CaseAction(tenant_id=case.tenant_id, case_id=case.id, action=action, from_status=from_status,
                      to_status=target, actor_id=user_id, justification=justification, payload=_safe(payload)))
    audit.record(db, tenant_id=case.tenant_id, actor_id=user_id, actor_role=role, action=f"case.{action}",
                 resource_type="case", resource_id=case.id,
                 details={"reference": case.reference, "from": from_status, "to": target, "justification": justification},
                 before={"status": from_status}, after={"status": target})
    db.flush()
    return case


def _assign(db: Session, case: Case, assignee_id, allowed_roles=(Role.COMPLIANCE_OFFICER, Role.COMPLIANCE_MANAGER)) -> None:
    try:
        uid = uuid.UUID(str(assignee_id))
    except ValueError:
        raise WorkflowError("assignee_id is not a valid id")
    user = db.get(User, uid)
    if user is None or user.tenant_id != case.tenant_id or not user.is_active:
        raise WorkflowError("Assignee not found")
    if user.role not in {r.value for r in allowed_roles}:
        raise WorkflowError(f"Assignee must have one of the roles: {', '.join(r.value for r in allowed_roles)}")
    case.assignee_id = uid


def _safe(payload: dict) -> dict:
    return {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v) for k, v in payload.items()}
