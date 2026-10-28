"""Turn ORM rows into API payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.treatment import TREATMENTS

from .models import (
    CaseAction,
    CaseRecord,
    Employer,
    EvaluationRun,
    EvidencePacket,
    FindingEvent,
    InputSnapshot,
    RiskEvidence,
    RiskFinding,
    RiskSignal,
    RuleDefinitionRow,
    RuleVersion,
)
from .services import cases as case_service


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def employer_names(db: Session, refs: set[str | None]) -> dict[str, str]:
    refs_clean = {r for r in refs if r}
    if not refs_clean:
        return {}
    return {
        e.source_employer_id: e.display_name
        for e in db.execute(
            select(Employer).where(Employer.is_current, Employer.source_employer_id.in_(refs_clean))
        ).scalars()
    }


def rule_titles(db: Session) -> dict[str, str]:
    return {r.rule_code: r.title for r in db.execute(select(RuleDefinitionRow)).scalars()}


def active_cases(db: Session, finding_ids: list[Any]) -> dict[Any, CaseRecord]:
    if not finding_ids:
        return {}
    out: dict[Any, CaseRecord] = {}
    for c in db.execute(
        select(CaseRecord).where(CaseRecord.finding_id.in_(finding_ids)).order_by(CaseRecord.created_at)
    ).scalars():
        out[c.finding_id] = c
    return out


def finding_summary(
    f: RiskFinding, names: dict[str, str], titles: dict[str, str], case: CaseRecord | None
) -> dict[str, Any]:
    return {
        "finding_id": str(f.id),
        "finding_ref": f.finding_ref,
        "tenant_id": str(f.tenant_id),
        "rule": {"id": f.rule_code, "version": f.rule_version},
        "title": titles.get(f.rule_code),
        "domain": f.domain,
        "signal_class": f.signal_class,
        "subject": {"type": f.subject_type, "id": f.subject_id, "employer_ref": f.employer_ref},
        "employer_name": names.get(f.employer_ref or ""),
        "lga": f.lga_code,
        "tax_type": f.tax_type,
        "tax_period": f.period_code,
        "status": f.status,
        "indicators": {"likelihood": f.likelihood, "consequence": f.consequence, "confidence": f.confidence},
        "priority_score": f.priority,
        "priority_band": f.priority_band,
        "priority_note": f.priority_note,
        "flags": {
            "data_hold": f.data_hold,
            "legal_hold": f.legal_hold,
            "disputed": f.disputed,
            "superseded": f.superseded_by_id is not None,
            "overridden": f.override is not None,
        },
        "holds": list(f.holds),
        "treatment": f.treatment,
        "allowed_next_action": f.allowed_next_action,
        "explanation": f.explanation,
        "case": {"id": str(case.id), "ref": case.case_ref, "stage": case.stage} if case else None,
        "version": f.version,
        "created_at": f.created_at.isoformat(),
        "label": "Risk indicator, not finding of evasion",
    }


def finding_detail(db: Session, f: RiskFinding) -> dict[str, Any]:
    names = employer_names(db, {f.employer_ref})
    case = active_cases(db, [f.id]).get(f.id)
    out = finding_summary(f, names, rule_titles(db), case)
    rv = db.get(RuleVersion, f.rule_version_id)
    snap = db.get(InputSnapshot, f.snapshot_id)
    run = db.get(EvaluationRun, f.run_id)
    evidence = list(db.execute(select(RiskEvidence).where(RiskEvidence.finding_id == f.id)).scalars())
    events = list(
        db.execute(
            select(FindingEvent).where(FindingEvent.finding_id == f.id).order_by(FindingEvent.occurred_at)
        ).scalars()
    )
    signals = list(
        db.execute(
            select(RiskSignal)
            .where(
                RiskSignal.rule_code == f.rule_code,
                RiskSignal.subject_id == f.subject_id,
                RiskSignal.period_code == f.period_code,
            )
            .limit(20)
        ).scalars()
    )
    definition = rv.expression_json if rv else {}
    supersedes = db.get(RiskFinding, f.supersedes_id) if f.supersedes_id else None
    superseded_by = db.get(RiskFinding, f.superseded_by_id) if f.superseded_by_id else None
    outcome = f.outcome or {}
    out.update(
        {
            "evidence_refs": list(f.evidence_refs),
            "gates": {
                "identity_verified": not any(
                    h in f.holds for h in ("identity_unverified", "identity_retracted")
                ),
                "legal_hold": f.legal_hold,
                "data_hold": f.data_hold,
                "disputed": f.disputed,
                "coverage_complete": not any(h == "coverage_incomplete" for h in f.holds),
            },
            "legal_version": f.legal_version_label,
            "matched_conditions": f.matched_conditions,
            "alternative_explanations": list(f.alternative_explanations),
            "evidence": [
                {"ref": e.source_record_ref, "field": e.field_name, "value": e.snapshot_value}
                for e in evidence
            ],
            "events": [
                {
                    "type": e.event_type,
                    "from": e.from_status,
                    "to": e.to_status,
                    "actor": e.actor_id,
                    "reason": e.reason,
                    "details": e.details,
                    "at": e.occurred_at.isoformat(),
                }
                for e in events
            ],
            "override": f.override,
            "rule_definition": definition,
            "snapshot": {
                "id": str(f.snapshot_id),
                "facts_hash": snap.facts_hash if snap else None,
                "as_of": _iso(snap.as_of) if snap else None,
                "run_id": str(f.run_id),
                "rule_set_hash": run.rule_set_hash if run else None,
                "rule_content_hash": rv.content_hash if rv else None,
            },
            "exclusions_checked": list(definition.get("exclusions", [])),
            "engine_outcome": {
                k: outcome.get(k) for k in ("likelihood", "consequence", "priority", "confidence")
            },
            "supersedes": supersedes.finding_ref if supersedes else None,
            "superseded_by": superseded_by.finding_ref if superseded_by else None,
            "signals": [
                {
                    "run_id": str(s.run_id),
                    "outcome": s.outcome,
                    "reasons": s.reasons,
                    "confidence": s.data_confidence,
                }
                for s in signals
            ],
        }
    )
    return out


def case_out(
    db: Session, c: CaseRecord, f: RiskFinding | None = None, names: dict[str, str] | None = None
) -> dict[str, Any]:
    f = f or db.get(RiskFinding, c.finding_id)
    names = names if names is not None else employer_names(db, {c.employer_ref})
    t = TREATMENTS.get(c.treatment)
    now = datetime.now(UTC)
    return {
        "id": str(c.id),
        "case_ref": c.case_ref,
        "finding_id": str(c.finding_id),
        "finding_ref": f.finding_ref if f else None,
        "rule_code": f.rule_code if f else None,
        "employer_ref": c.employer_ref,
        "employer_name": names.get(c.employer_ref or ""),
        "lga": f.lga_code if f else None,
        "tax_period": f.period_code if f else None,
        "treatment": c.treatment,
        "treatment_label": t.label if t else None,
        "stage": c.stage,
        "outcome": c.outcome,
        "assigned_to": c.assigned_to,
        "created_by": c.created_by,
        "approved_by": c.approved_by,
        "approved_at": _iso(c.approved_at),
        "due_at": _iso(c.due_at),
        "overdue": bool(c.due_at and c.due_at < now and c.stage not in ("closed", "rejected")),
        "legal_hold": c.legal_hold,
        "outward_permitted": c.outward_permitted,
        "outward_blockers": case_service.outward_blockers(db, c, f) if f else [],
        "rationale": c.rationale,
        "version": c.version,
        "created_at": c.created_at.isoformat(),
    }


def case_detail(db: Session, c: CaseRecord) -> dict[str, Any]:
    f = db.get(RiskFinding, c.finding_id)
    out = case_out(db, c, f)
    actions = list(
        db.execute(
            select(CaseAction).where(CaseAction.case_id == c.id).order_by(CaseAction.acted_at)
        ).scalars()
    )
    packets = list(db.execute(select(EvidencePacket).where(EvidencePacket.case_id == c.id)).scalars())
    names = employer_names(db, {c.employer_ref})
    out["actions"] = [
        {
            "id": str(a.id),
            "type": a.action_type,
            "detail": a.detail,
            "template": a.template_code,
            "delivery_status": a.delivery_status,
            "actor": a.actor_id,
            "approved_by": a.approved_by,
            "evidence_ref": a.evidence_ref,
            "outcome": a.outcome,
            "next_due_at": _iso(a.next_due_at),
            "at": a.acted_at.isoformat(),
        }
        for a in actions
    ]
    out["finding"] = finding_summary(f, names, rule_titles(db), c) if f else None
    out["packets"] = [
        {
            "sha256": p.sha256,
            "exported_by": p.exported_by,
            "purpose": p.purpose,
            "at": p.created_at.isoformat(),
        }
        for p in packets
    ]
    return out


def run_out(db: Session, r: EvaluationRun) -> dict[str, Any]:
    snap = db.get(InputSnapshot, r.snapshot_id)
    versions = (
        list(db.execute(select(RuleVersion).where(RuleVersion.id.in_(r.rule_version_ids))).scalars())
        if r.rule_version_ids
        else []
    )
    return {
        "id": str(r.id),
        "mode": r.mode,
        "status": r.status,
        "as_of": r.as_of.isoformat(),
        "period_from": r.period_from,
        "period_to": r.period_to,
        "rule_set_hash": r.rule_set_hash,
        "snapshot_hash": snap.facts_hash if snap else None,
        "rule_versions": sorted(f"{v.rule_code}@{v.version}" for v in versions),
        "counts": r.counts,
        "outcome_digest": r.outcome_digest,
        "triggered_by": r.triggered_by,
        "started_at": r.started_at.isoformat(),
        "finished_at": _iso(r.finished_at),
    }
