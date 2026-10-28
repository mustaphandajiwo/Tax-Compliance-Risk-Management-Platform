"""Case / treatment workflow with human approval gates (FR-012, FR-015, FR-017).

Outward (taxpayer-facing) actions are allowed only when the approved case's
finding is free of data holds, legal holds, disputes and identity doubts, the
tenant is in operational (not shadow) mode, and the treatment is one that
involves contact. Even then, demo environments never send anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.hashing import canonical_json, sha256_hex
from risk_engine.states import TERMINAL_FINDING_STATES, check_case_transition
from risk_engine.treatment import TREATMENTS

from .. import audit
from ..config import get_settings
from ..errors import conflict, forbidden, not_found, unprocessable
from ..models import (
    AuditEvent,
    CaseAction,
    CaseRecord,
    EvidencePacket,
    FindingEvent,
    RiskEvidence,
    RiskFinding,
    RuleVersion,
    Tenant,
)
from ..security import crypto
from ..security.auth import Principal
from ..storage import get_store
from .findings import check_version, transition

ACTION_TYPES = {
    "note",
    "contact_taxpayer",
    "taxpayer_response",
    "payment_evidence_attached",
    "reconciliation_completed",
    "audit_finding",
    "escalate",
    "assistance_provided",
}
FINAL_FINDING_OUTCOMES = {"closed_confirmed", "closed_not_substantiated", "corrected", "withdrawn"}


def _case_ref(db: Session) -> str:
    n = len(list(db.execute(select(CaseRecord.id)).scalars())) + 1
    return f"CASE-{datetime.now(UTC):%Y}-{n:05d}-{uuid.uuid4().hex[:4].upper()}"


def outward_blockers(db: Session, case: CaseRecord, f: RiskFinding) -> list[str]:
    blockers = []
    t = TREATMENTS.get(case.treatment)
    if t is None or not t.outward:
        blockers.append("treatment_is_internal")
    if f.data_hold:
        blockers.append("data_hold")
    if f.legal_hold or case.legal_hold:
        blockers.append("legal_hold")
    if f.disputed:
        blockers.append("disputed")
    if any(h in f.holds for h in ("identity_unverified", "identity_retracted")):
        blockers.append("identity_unverified")
    if f.signal_class == "data_quality":
        blockers.append("data_quality_signal")
    tenant = db.get(Tenant, case.tenant_id)
    if ((tenant.settings if tenant else {}) or {}).get("operating_mode", "shadow") != "operational":
        blockers.append("shadow_mode")
    return blockers


def create(
    db: Session,
    actor: Principal,
    finding: RiskFinding,
    treatment: str | None,
    rationale: str,
    assigned_to: str | None,
    sla_days: int,
) -> CaseRecord:
    if finding.status in TERMINAL_FINDING_STATES:
        raise conflict(f"Finding is {finding.status}")
    if finding.superseded_by_id is not None:
        raise conflict("Finding is superseded by a newer rule version")
    code = treatment or finding.treatment
    t = TREATMENTS.get(code or "")
    if t is None:
        raise unprocessable(f"Unknown treatment {code}")
    if finding.data_hold and t.outward:
        raise conflict("Data-hold findings can only take internal treatments (verify data first)")
    if not rationale.strip():
        raise unprocessable("A rationale is required")
    existing = db.execute(
        select(CaseRecord).where(
            CaseRecord.finding_key == finding.finding_key, CaseRecord.stage.notin_(["closed", "rejected"])
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise conflict(
            f"An active case already exists for this finding: {existing.case_ref}",
            {"case_id": str(existing.id)},
        )
    case = CaseRecord(
        tenant_id=actor.tenant_id,
        case_ref=_case_ref(db),
        finding_id=finding.id,
        finding_key=finding.finding_key,
        employer_id=finding.employer_id,
        employer_ref=finding.employer_ref,
        treatment=t.code,
        stage="pending_approval",
        assigned_to=assigned_to,
        created_by=actor.actor_id,
        due_at=datetime.now(UTC) + timedelta(days=sla_days),
        sla_days=sla_days,
        legal_hold=finding.legal_hold,
        rationale=rationale,
    )
    db.add(case)
    db.flush()
    audit.record(
        db,
        actor,
        "case.created",
        f"case:{case.case_ref}",
        {"finding": finding.finding_ref, "treatment": t.code, "assigned_to": assigned_to},
    )
    return case


def approve(
    db: Session, actor: Principal, case: CaseRecord, note: str, expected_version: int | None
) -> CaseRecord:
    check_version(case, expected_version)
    check_case_transition(case.stage, "approved")
    if case.created_by == actor.actor_id:
        raise forbidden("Segregation of duties: the case creator cannot approve it")
    t = TREATMENTS[case.treatment]
    if not any(r in actor.roles for r in t.approver_roles):
        raise forbidden(f"Treatment '{t.label}' must be approved by: {', '.join(t.approver_roles)}")
    f = db.get(RiskFinding, case.finding_id)
    assert f is not None
    if f.status in TERMINAL_FINDING_STATES:
        raise conflict(f"Finding is {f.status}")
    blockers = outward_blockers(db, case, f)
    case.stage = "approved"
    case.approved_by = actor.actor_id
    case.approved_at = datetime.now(UTC)
    case.approval_note = note
    case.outward_permitted = not blockers
    case.version += 1
    if f.status == "review_required":
        transition(db, f, "approved_for_treatment", actor.actor_id, f"case {case.case_ref} approved")
        f.version += 1
    db.flush()
    audit.record(
        db,
        actor,
        "case.approved",
        f"case:{case.case_ref}",
        {"note": note, "outward_permitted": case.outward_permitted, "blockers": blockers},
    )
    return case


def reject(
    db: Session, actor: Principal, case: CaseRecord, note: str, expected_version: int | None
) -> CaseRecord:
    check_version(case, expected_version)
    check_case_transition(case.stage, "rejected")
    if case.created_by == actor.actor_id:
        raise forbidden("Segregation of duties: the case creator cannot decide it")
    case.stage = "rejected"
    case.approval_note = note
    case.closed_at = datetime.now(UTC)
    case.version += 1
    db.flush()
    audit.record(db, actor, "case.rejected", f"case:{case.case_ref}", {"note": note})
    return case


def assign(
    db: Session, actor: Principal, case: CaseRecord, assignee: str, expected_version: int | None
) -> None:
    check_version(case, expected_version)
    before = case.assigned_to
    case.assigned_to = assignee
    case.version += 1
    db.flush()
    audit.record(db, actor, "case.assigned", f"case:{case.case_ref}", {"from": before, "to": assignee})


def add_action(db: Session, actor: Principal, case: CaseRecord, data: dict[str, Any]) -> CaseAction:
    check_version(case, data.get("expected_version"))
    action_type = data["action_type"]
    if action_type not in ACTION_TYPES:
        raise unprocessable(f"Unknown action type {action_type}", {"allowed": sorted(ACTION_TYPES)})
    if case.stage in ("pending_approval", "closed", "rejected"):
        raise conflict(f"Case is {case.stage}; actions need an approved, open case")
    f = db.get(RiskFinding, case.finding_id)
    assert f is not None
    if action_type == "audit_finding" and "audit_officer" not in actor.roles:
        raise forbidden("Only audit officers record audit findings")
    delivery = None
    template = data.get("template_code")
    if action_type == "contact_taxpayer":
        blockers = outward_blockers(db, case, f)
        if not case.outward_permitted or blockers:
            raise conflict("Taxpayer contact is not permitted for this case", {"blockers": blockers})
        tenant = db.get(Tenant, case.tenant_id)
        templates = ((tenant.settings if tenant else {}) or {}).get("approved_templates", {})
        if template not in templates:
            raise unprocessable("Use an approved communication template", {"approved": sorted(templates)})
        s = get_settings()
        delivery = (
            "queued" if s.outbound_messaging_enabled and not s.is_demo() else "not_sent_demo_environment"
        )
    action = CaseAction(
        tenant_id=case.tenant_id,
        case_id=case.id,
        action_type=action_type,
        detail=data.get("detail", ""),
        template_code=template,
        delivery_status=delivery,
        actor_id=actor.actor_id,
        approved_by=case.approved_by if action_type == "contact_taxpayer" else None,
        evidence_ref=data.get("evidence_ref"),
        outcome=data.get("outcome"),
        next_due_at=data.get("next_due_at"),
    )
    db.add(action)
    if case.stage == "approved":
        case.stage = "in_progress"
    if action_type == "contact_taxpayer":
        case.stage = "awaiting_response"
        if f.status == "approved_for_treatment":
            transition(db, f, "treated", actor.actor_id, f"{case.case_ref}: taxpayer contacted")
            f.version += 1
    elif action_type == "taxpayer_response" and case.stage == "awaiting_response":
        case.stage = "in_progress"
    if data.get("next_due_at"):
        case.due_at = data["next_due_at"]
    case.version += 1
    db.flush()
    audit.record(
        db,
        actor,
        f"case.action.{action_type}",
        f"case:{case.case_ref}",
        {
            "detail": action.detail,
            "template": template,
            "delivery_status": delivery,
            "evidence_ref": action.evidence_ref,
        },
    )
    return action


def close(
    db: Session,
    actor: Principal,
    case: CaseRecord,
    finding_outcome: str,
    note: str,
    expected_version: int | None,
) -> CaseRecord:
    check_version(case, expected_version)
    if finding_outcome not in FINAL_FINDING_OUTCOMES:
        raise unprocessable(f"finding_outcome must be one of {sorted(FINAL_FINDING_OUTCOMES)}")
    check_case_transition(case.stage, "closed")
    f = db.get(RiskFinding, case.finding_id)
    assert f is not None
    if f.status not in TERMINAL_FINDING_STATES:
        transition(db, f, finding_outcome, actor.actor_id, f"{case.case_ref} closed: {note}")
        f.version += 1
    case.stage = "closed"
    case.outcome = finding_outcome
    case.closed_at = datetime.now(UTC)
    case.version += 1
    db.flush()
    audit.record(
        db, actor, "case.closed", f"case:{case.case_ref}", {"finding_outcome": finding_outcome, "note": note}
    )
    return case


def evidence_packet(db: Session, actor: Principal, case: CaseRecord, purpose: str) -> dict[str, Any]:
    f = db.get(RiskFinding, case.finding_id)
    assert f is not None
    rv = db.get(RuleVersion, f.rule_version_id)
    evidence = list(db.execute(select(RiskEvidence).where(RiskEvidence.finding_id == f.id)).scalars())
    events = list(
        db.execute(
            select(FindingEvent).where(FindingEvent.finding_id == f.id).order_by(FindingEvent.occurred_at)
        ).scalars()
    )
    actions = list(
        db.execute(
            select(CaseAction).where(CaseAction.case_id == case.id).order_by(CaseAction.acted_at)
        ).scalars()
    )
    audits = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.subject_ref.in_([f"case:{case.case_ref}", f"finding:{f.finding_ref}"]))
            .order_by(AuditEvent.seq)
        ).scalars()
    )
    packet = {
        "packet_type": "ngsirs.desk_review.evidence/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": actor.actor_id,
        "purpose": purpose,
        "environment": get_settings().environment,
        "synthetic_data": get_settings().is_demo(),
        "notice": "Risk indicator, not finding of evasion. Internal desk-review evidence only.",
        "case": {
            "ref": case.case_ref,
            "stage": case.stage,
            "treatment": case.treatment,
            "approved_by": case.approved_by,
            "rationale": case.rationale,
        },
        "finding": {
            "ref": f.finding_ref,
            "rule": f"{f.rule_code}@{f.rule_version}",
            "rule_content_hash": rv.content_hash if rv else None,
            "legal_version": f.legal_version_label,
            "subject": f"{f.subject_type}:{f.subject_id}",
            "period": f.period_code,
            "status": f.status,
            "likelihood": f.likelihood,
            "consequence": f.consequence,
            "confidence": f.confidence,
            "priority": f.priority,
            "holds": f.holds,
            "explanation": f.explanation,
            "alternative_explanations": f.alternative_explanations,
            "matched_conditions": f.matched_conditions,
            "override": f.override,
            "snapshot_id": str(f.snapshot_id),
            "run_id": str(f.run_id),
        },
        "evidence": [
            {"ref": e.source_record_ref, "field": e.field_name, "value": e.snapshot_value} for e in evidence
        ],
        "decision_trail": [
            {
                "type": e.event_type,
                "from": e.from_status,
                "to": e.to_status,
                "actor": e.actor_id,
                "reason": e.reason,
                "at": e.occurred_at.isoformat(),
            }
            for e in events
        ],
        "actions": [
            {
                "type": a.action_type,
                "detail": a.detail,
                "actor": a.actor_id,
                "at": a.acted_at.isoformat(),
                "delivery_status": a.delivery_status,
            }
            for a in actions
        ],
        "audit_chain": [{"seq": a.seq, "type": a.event_type, "hash": a.event_hash} for a in audits],
    }
    body = canonical_json(packet).encode()
    digest = sha256_hex(body)
    signature = crypto.sign(body)
    key = f"{case.tenant_id}/evidence/{case.case_ref}/{digest}.json"
    get_store().put(key, body)
    db.add(
        EvidencePacket(
            tenant_id=case.tenant_id,
            case_id=case.id,
            sha256=digest,
            signature=signature,
            key_id=crypto.signing_key_id(),
            exported_by=actor.actor_id,
            purpose=purpose,
            object_key=key,
        )
    )
    db.flush()
    audit.record(db, actor, "evidence.exported", f"case:{case.case_ref}", {"sha256": digest}, purpose=purpose)
    return {
        "packet": packet,
        "sha256": digest,
        "signature": signature,
        "key_id": crypto.signing_key_id(),
        "algorithm": "Ed25519",
    }


def get_case(db: Session, case_id: uuid.UUID) -> CaseRecord:
    c = db.get(CaseRecord, case_id)
    if c is None:
        raise not_found("Case")
    return c
