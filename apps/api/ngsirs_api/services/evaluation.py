"""Evaluation runs (Tech Spec section 8).

An operational run freezes an immutable input snapshot, evaluates every
active rule version once per eligible subject and period, and upserts findings
idempotently: the same rule version + subject + period never produces a second
finding, and replaying an identical snapshot with an identical rule set reuses
the earlier run. Every finding records the rule version, legal version, tax
period and snapshot it came from, so ``reproduce`` can recompute it exactly.
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine import Outcome, RuleDefinition, evaluate, validate_rule
from risk_engine.facts import FactRecord
from risk_engine.hashing import canonical_json, rule_set_hash, sha256_hex
from risk_engine.states import OPEN_FINDING_STATES, TERMINAL_FINDING_STATES

from .. import audit
from ..errors import conflict, not_found, unprocessable
from ..models import (
    CaseRecord,
    Employer,
    EvaluationRun,
    FindingEvent,
    InputSnapshot,
    LegalRuleVersion,
    RiskEvidence,
    RiskFinding,
    RiskSignal,
    RuleDefinitionRow,
    RuleVersion,
    Tenant,
)
from ..security.auth import Principal
from ..storage import get_store
from . import facts as facts_builder
from . import legal

SYSTEM_ACTOR = "system:risk-engine"


def finding_key(o: Outcome) -> str:
    return f"{o.rule_code}|{o.subject_type}:{o.subject_id}|{o.period or '-'}"


def finding_ref(tenant_id: uuid.UUID, key: str, rule_version: str) -> str:
    return "RF-" + sha256_hex(f"{tenant_id}|{key}|{rule_version}")[:10].upper()


def outcome_hash(o: Outcome) -> str:
    return sha256_hex(o.to_dict())


def _store_snapshot(
    db: Session,
    tenant: Tenant,
    as_of: datetime,
    period_from: str,
    period_to: str,
    records: list[FactRecord],
    batch_ids: list[str],
) -> InputSnapshot:
    body = canonical_json(
        {"as_of": as_of.isoformat(), "period_from": period_from, "period_to": period_to, "records": records}
    )
    digest = sha256_hex(body.encode())
    existing = db.execute(
        select(InputSnapshot).where(InputSnapshot.facts_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    key = f"{tenant.id}/snapshots/{digest}.json.gz"
    get_store().put(key, gzip.compress(body.encode(), mtime=0))
    snap = InputSnapshot(
        tenant_id=tenant.id,
        as_of=as_of,
        batch_ids=batch_ids,
        facts_hash=digest,
        object_key=key,
        record_count=len(records),
        period_from=period_from,
        period_to=period_to,
    )
    db.add(snap)
    db.flush()
    return snap


def load_snapshot(snap: InputSnapshot) -> list[FactRecord]:
    body = gzip.decompress(get_store().get(snap.object_key))
    if sha256_hex(body) != snap.facts_hash:
        raise conflict("Snapshot content does not match its recorded hash")
    data: dict[str, Any] = json.loads(body)
    records: list[FactRecord] = data["records"]
    return records


def active_rule_versions(db: Session) -> list[RuleVersion]:
    ids = [
        r.active_version_id for r in db.execute(select(RuleDefinitionRow)).scalars() if r.active_version_id
    ]
    if not ids:
        return []
    return list(
        db.execute(
            select(RuleVersion).where(RuleVersion.id.in_(ids)).order_by(RuleVersion.rule_code)
        ).scalars()
    )


def _legal_inputs(db: Session) -> list[dict[str, Any]]:
    return [
        {"code": v.code, "version": v.version, "hash": v.content_hash, "status": v.status}
        for v in db.execute(select(LegalRuleVersion).where(LegalRuleVersion.status == "approved")).scalars()
    ]


def _evaluate_all(
    rules: list[tuple[RuleVersion, RuleDefinition]], records: list[FactRecord], confidence_floor: float
) -> list[tuple[RuleVersion, RuleDefinition, FactRecord, Outcome]]:
    by_kind: dict[str, list[FactRecord]] = defaultdict(list)
    for r in records:
        by_kind[r["kind"]].append(r)
    out = []
    for rv, rule in rules:
        for rec in by_kind.get(rule.scope.fact_kind, []):
            o = evaluate(rule, rec, confidence_floor)
            leg = (rec.get("legal_versions") or {}).get((rule.obligation_ref or "").split("@")[0])
            o.legal_version = leg["label"] if leg else None
            out.append((rv, rule, rec, o))
    return out


def outcome_digest(outcomes: list[tuple[Any, Any, Any, Outcome]]) -> str:
    return sha256_hex(
        sorted(
            f"{finding_key(o)}|{o.rule_version}|{outcome_hash(o)}" for _, _, _, o in outcomes if o.is_finding
        )
    )


def _counts(outcomes: list[tuple[Any, Any, Any, Outcome]]) -> dict[str, Any]:
    per_rule: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: Counter[str] = Counter()
    holds: Counter[str] = Counter()
    for _, _, _, o in outcomes:
        per_rule[o.rule_code][o.outcome] += 1
        if o.outcome == "suppressed":
            reasons.update(o.reasons)
        if o.is_finding:
            if o.data_hold:
                per_rule[o.rule_code]["data_hold"] += 1
            holds.update(o.holds)
    findings = sum(1 for *_, o in outcomes if o.is_finding)
    held = sum(1 for *_, o in outcomes if o.is_finding and o.data_hold)
    return {
        "rules": {k: dict(v) for k, v in sorted(per_rule.items())},
        "suppression_reasons": dict(reasons),
        "hold_reasons": dict(holds),
        "findings": findings,
        "data_holds": held,
        "hold_rate": round(held / findings, 4) if findings else 0.0,
    }


def run_evaluation(
    db: Session,
    actor: Principal | str,
    tenant_id: uuid.UUID,
    *,
    as_of: datetime,
    period_from: str,
    period_to: str,
    idempotency_key: str | None = None,
) -> tuple[EvaluationRun, bool]:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise not_found("Tenant")
    if as_of > datetime.now(UTC):
        raise unprocessable("as_of cannot be in the future")
    if period_from > period_to:
        raise unprocessable("period_from is after period_to")
    periods = legal.period_range(period_from, period_to)
    legal.ensure_schedules(db, tenant.id, periods)
    versions = active_rule_versions(db)
    if not versions:
        raise conflict("No approved and active rule versions; activate rules in Rule Configuration first")
    rules = [(rv, validate_rule(rv.expression_json)) for rv in versions]
    records, batch_ids = facts_builder.build(db, tenant, as_of, period_from, period_to)
    snap = _store_snapshot(db, tenant, as_of, period_from, period_to, records, batch_ids)
    rs_hash = rule_set_hash([rv.expression_json for rv in versions], _legal_inputs(db))

    # Replaying exactly the latest run (same snapshot, same rule set) is a no-op. An identical snapshot from an
    # older run is not: findings may have changed since, so it is evaluated again (still idempotently).
    latest = (
        db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.mode == "operational", EvaluationRun.status == "completed")
            .order_by(EvaluationRun.finished_at.desc())
        )
        .scalars()
        .first()
    )
    if latest is not None and latest.rule_set_hash == rs_hash and latest.snapshot_id == snap.id:
        return latest, False

    actor_id = actor.actor_id if isinstance(actor, Principal) else actor
    run = EvaluationRun(
        tenant_id=tenant.id,
        mode="operational",
        rule_set_hash=rs_hash,
        rule_version_ids=[str(v.id) for v in versions],
        snapshot_id=snap.id,
        period_from=period_from,
        period_to=period_to,
        as_of=as_of,
        status="running",
        triggered_by=actor_id,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()

    floor = float((tenant.settings or {}).get("confidence_floor", 0.9))
    outcomes = _evaluate_all(rules, records, floor)
    employers = {
        e.source_employer_id: e for e in db.execute(select(Employer).where(Employer.is_current)).scalars()
    }
    _persist(db, tenant, run, snap, outcomes, employers)
    run.counts = _counts(outcomes)
    run.outcome_digest = outcome_digest(outcomes)
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    db.flush()
    details = {
        "as_of": as_of.isoformat(),
        "periods": [period_from, period_to],
        "rule_set_hash": rs_hash,
        "snapshot": snap.facts_hash,
        "findings": run.counts["findings"],
        "data_holds": run.counts["data_holds"],
    }
    if isinstance(actor, Principal):
        audit.record(db, actor, "evaluation.completed", f"run:{run.id}", details)
    else:
        audit.record(db, actor, "evaluation.completed", f"run:{run.id}", details, tenant_id=tenant.id)
    return run, True


def _persist(
    db: Session,
    tenant: Tenant,
    run: EvaluationRun,
    snap: InputSnapshot,
    outcomes: list[tuple[RuleVersion, RuleDefinition, FactRecord, Outcome]],
    employers: dict[str, Employer],
) -> None:
    existing: dict[str, list[RiskFinding]] = defaultdict(list)
    for f in db.execute(select(RiskFinding)).scalars():
        existing[f.finding_key].append(f)
    active_case_findings = set(
        db.execute(
            select(CaseRecord.finding_id).where(CaseRecord.stage.notin_(["closed", "rejected"]))
        ).scalars()
    )
    now = datetime.now(UTC)
    evaluated_codes = {rv.rule_code for rv, *_ in outcomes}
    seen_keys: set[str] = set()

    for rv, rule, rec, o in outcomes:
        if o.outcome == "suppressed":
            db.add(
                RiskSignal(
                    tenant_id=tenant.id,
                    run_id=run.id,
                    rule_version_id=rv.id,
                    rule_code=o.rule_code,
                    subject_type=o.subject_type,
                    subject_id=o.subject_id,
                    period_code=o.period,
                    outcome=o.outcome,
                    reasons=o.reasons,
                    data_confidence=o.confidence,
                )
            )
            seen_keys.add(finding_key(o))  # cannot tell now: leave any open finding untouched
            continue
        if not o.is_finding:
            continue
        key = finding_key(o)
        seen_keys.add(key)
        db.add(
            RiskSignal(
                tenant_id=tenant.id,
                run_id=run.id,
                rule_version_id=rv.id,
                rule_code=o.rule_code,
                subject_type=o.subject_type,
                subject_id=o.subject_id,
                period_code=o.period,
                outcome=o.outcome,
                reasons=o.holds,
                data_confidence=o.confidence,
            )
        )
        o_hash = outcome_hash(o)
        same_version = next((f for f in existing[key] if f.rule_version_id == rv.id), None)
        employer_ref = o.subject_id if o.subject_type == "employer" else rec.get("employer_ref")
        emp = employers.get(employer_ref or "")
        if same_version is not None and same_version.superseded_by_id is not None:
            _revive_after_rollback(db, tenant, same_version, active_case_findings, o)
        if same_version is not None:
            same_version.last_seen_run_id = run.id
            if same_version.outcome_hash != o_hash and same_version.status not in TERMINAL_FINDING_STATES:
                db.add(
                    FindingEvent(
                        tenant_id=tenant.id,
                        finding_id=same_version.id,
                        event_type="rescored",
                        actor_id=SYSTEM_ACTOR,
                        details={
                            "previous_outcome_hash": same_version.outcome_hash,
                            "previous_run_id": str(same_version.run_id),
                            "previous": {
                                "likelihood": same_version.likelihood,
                                "consequence": same_version.consequence,
                                "priority": same_version.priority,
                                "holds": same_version.holds,
                            },
                        },
                    )
                )
                _apply(same_version, o, o_hash, run, snap)
                same_version.version += 1
                same_version.updated_at = now
            continue
        previous_open = next(
            (f for f in existing[key] if f.status in OPEN_FINDING_STATES and f.superseded_by_id is None), None
        )
        finding = RiskFinding(
            tenant_id=tenant.id,
            finding_ref=finding_ref(tenant.id, key, o.rule_version),
            finding_key=key,
            rule_code=o.rule_code,
            rule_version_id=rv.id,
            rule_version=o.rule_version,
            tax_type=rule.scope.tax_type,
            domain=rule.domain,
            subject_type=o.subject_type,
            subject_id=o.subject_id,
            employer_id=emp.id if emp else None,
            employer_ref=employer_ref,
            lga_code=rec.get("lga_code"),
            period_code=o.period,
            status="review_required",
            effort=rule.signal.effort,
            first_run_id=run.id,
            last_seen_run_id=run.id,
            run_id=run.id,
            snapshot_id=snap.id,
            explanation="",
            outcome={},
            outcome_hash="",
            supersedes_id=previous_open.id if previous_open else None,
        )
        _apply(finding, o, o_hash, run, snap)
        db.add(finding)
        db.flush()
        existing[key].append(finding)
        for status_from, status_to in (("candidate", "validated"), ("validated", "review_required")):
            db.add(
                FindingEvent(
                    tenant_id=tenant.id,
                    finding_id=finding.id,
                    event_type="state_change",
                    from_status=status_from,
                    to_status=status_to,
                    actor_id=SYSTEM_ACTOR,
                    details={"run_id": str(run.id)},
                )
            )
        for ref in o.evidence_refs:
            db.add(RiskEvidence(tenant_id=tenant.id, finding_id=finding.id, source_record_ref=ref))
        for field_name, value in o.evidence_values.items():
            db.add(
                RiskEvidence(
                    tenant_id=tenant.id,
                    finding_id=finding.id,
                    source_record_ref="snapshot:" + snap.facts_hash[:16],
                    field_name=field_name,
                    snapshot_value=json.dumps(value),
                    value_hash=sha256_hex(value),
                )
            )
        if previous_open is not None:
            previous_open.superseded_by_id = finding.id
            previous_open.version += 1
            if previous_open.id not in active_case_findings and previous_open.status == "review_required":
                previous_open.status = "withdrawn"
                db.add(
                    FindingEvent(
                        tenant_id=tenant.id,
                        finding_id=previous_open.id,
                        event_type="state_change",
                        from_status="review_required",
                        to_status="withdrawn",
                        actor_id=SYSTEM_ACTOR,
                        reason=f"superseded by {o.rule_code} {o.rule_version}",
                    )
                )

    # Findings whose condition is no longer met (e.g. the return arrived) are withdrawn in the taxpayer's
    # favour, but only while still awaiting review with no case attached.
    for key, rows in existing.items():
        if key in seen_keys:
            continue
        for f in rows:
            if (
                f.rule_code in evaluated_codes
                and f.status == "review_required"
                and f.superseded_by_id is None
                and f.id not in active_case_findings
                and f.period_code is not None
                and run.period_from <= f.period_code <= run.period_to
            ):
                f.status = "withdrawn"
                f.version += 1
                db.add(
                    FindingEvent(
                        tenant_id=tenant.id,
                        finding_id=f.id,
                        event_type="state_change",
                        from_status="review_required",
                        to_status="withdrawn",
                        actor_id=SYSTEM_ACTOR,
                        reason="condition no longer met",
                        details={"run_id": str(run.id)},
                    )
                )
    db.flush()


def _revive_after_rollback(
    db: Session, tenant: Tenant, f: RiskFinding, active_case_findings: set[Any], o: Outcome
) -> None:
    """The rule was rolled back to this finding's version: make it current again.

    The finding from the rolled-back version is withdrawn unless a case is already working on it, in which
    case that case continues and this finding stays superseded.
    """
    newer = db.get(RiskFinding, f.superseded_by_id)
    if newer is not None and (
        newer.id in active_case_findings
        or newer.status in TERMINAL_FINDING_STATES
        and newer.status != "withdrawn"
    ):
        return
    reason = f"rule {o.rule_code} rolled back to {o.rule_version}"
    if newer is not None and newer.status in OPEN_FINDING_STATES:
        db.add(
            FindingEvent(
                tenant_id=tenant.id,
                finding_id=newer.id,
                event_type="state_change",
                from_status=newer.status,
                to_status="withdrawn",
                actor_id=SYSTEM_ACTOR,
                reason=reason,
            )
        )
        newer.status = "withdrawn"
        newer.superseded_by_id = f.id
        newer.version += 1
    f.superseded_by_id = None
    f.supersedes_id = newer.id if newer is not None else f.supersedes_id
    if f.status == "withdrawn":
        db.add(
            FindingEvent(
                tenant_id=tenant.id,
                finding_id=f.id,
                event_type="state_change",
                from_status="withdrawn",
                to_status="review_required",
                actor_id=SYSTEM_ACTOR,
                reason=reason,
            )
        )
        f.status = "review_required"
    f.version += 1


def _apply(f: RiskFinding, o: Outcome, o_hash: str, run: EvaluationRun, snap: InputSnapshot) -> None:
    officer_markers = [h for h in (f.holds or []) if h.startswith("officer_")]
    f.signal_class = o.signal_class or "taxpayer_risk"
    f.likelihood, f.consequence, f.confidence = o.likelihood, o.consequence, o.confidence
    f.priority, f.priority_band, f.priority_note = o.priority, o.priority_band, o.priority_note
    f.holds = [*o.holds, *officer_markers]
    f.data_hold = o.data_hold
    f.legal_hold = o.legal_hold or "officer_legal_hold" in officer_markers
    f.disputed = o.disputed or f.disputed
    f.treatment = o.treatment
    f.allowed_next_action = o.allowed_next_action
    f.explanation = o.explanation or ""
    f.alternative_explanations = o.alternative_explanations
    f.matched_conditions = o.matched_conditions
    f.evidence_refs = o.evidence_refs
    f.legal_version_label = o.legal_version
    f.outcome = o.to_dict()
    f.outcome_hash = o_hash
    f.run_id = run.id
    f.snapshot_id = snap.id
    if f.override:
        # A manager override stays on top of rescoring until removed; the engine values remain in `outcome`.
        f.likelihood = f.override.get("likelihood", f.likelihood)
        f.consequence = f.override.get("consequence", f.consequence)
        f.priority = (4 * f.likelihood * f.consequence) if f.likelihood and f.consequence else None


def reproduce_finding(db: Session, finding: RiskFinding) -> dict[str, Any]:
    snap = db.get(InputSnapshot, finding.snapshot_id)
    rv = db.get(RuleVersion, finding.rule_version_id)
    run = db.get(EvaluationRun, finding.run_id)
    assert snap and rv and run
    tenant = db.get(Tenant, finding.tenant_id)
    floor = float(((tenant.settings if tenant else {}) or {}).get("confidence_floor", 0.9))
    rule = validate_rule(rv.expression_json)
    records = load_snapshot(snap)
    target = next(
        (
            r
            for r in records
            if r["kind"] == rule.scope.fact_kind
            and r["subject_id"] == finding.subject_id
            and r.get("period") == finding.period_code
        ),
        None,
    )
    if target is None:
        return {"reproduced": False, "reason": "subject not present in snapshot"}
    ((_, _, _, o),) = _evaluate_all([(rv, rule)], [target], floor)
    h = outcome_hash(o)
    return {
        "reproduced": h == finding.outcome_hash,
        "outcome_hash": h,
        "stored_outcome_hash": finding.outcome_hash,
        "rule": f"{rv.rule_code}@{rv.version}",
        "rule_content_hash": rv.content_hash,
        "snapshot": snap.facts_hash,
        "run_id": str(run.id),
        "rule_set_hash": run.rule_set_hash,
        "outcome": o.to_dict(),
    }


def reproduce_run(db: Session, run: EvaluationRun) -> dict[str, Any]:
    snap = db.get(InputSnapshot, run.snapshot_id)
    assert snap is not None
    tenant = db.get(Tenant, run.tenant_id)
    floor = float(((tenant.settings if tenant else {}) or {}).get("confidence_floor", 0.9))
    versions = list(
        db.execute(
            select(RuleVersion).where(RuleVersion.id.in_([uuid.UUID(i) for i in run.rule_version_ids]))
        ).scalars()
    )
    rules = [(rv, validate_rule(rv.expression_json)) for rv in versions]
    outcomes = _evaluate_all(rules, load_snapshot(snap), floor)
    digest = outcome_digest(outcomes)
    return {
        "run_id": str(run.id),
        "reproduced": digest == run.outcome_digest,
        "outcome_digest": digest,
        "stored_outcome_digest": run.outcome_digest,
        "snapshot": snap.facts_hash,
        "rule_versions": sorted(f"{v.rule_code}@{v.version}" for v in versions),
    }


def backtest(
    db: Session, actor: Principal, rv: RuleVersion, *, as_of: datetime, period_from: str, period_to: str
) -> dict[str, Any]:
    """Shadow-evaluate a candidate version and compare with the active one. Writes no findings."""
    tenant = db.get(Tenant, actor.tenant_id)
    assert tenant is not None
    legal.ensure_schedules(db, tenant.id, legal.period_range(period_from, period_to))
    candidate = validate_rule(rv.expression_json)
    records, _ = facts_builder.build(db, tenant, as_of, period_from, period_to)
    floor = float((tenant.settings or {}).get("confidence_floor", 0.9))
    cand_out = _evaluate_all([(rv, candidate)], records, floor)
    definition = db.execute(
        select(RuleDefinitionRow).where(RuleDefinitionRow.rule_code == rv.rule_code)
    ).scalar_one_or_none()
    active = (
        db.get(RuleVersion, definition.active_version_id)
        if definition and definition.active_version_id
        else None
    )
    base_out = (
        _evaluate_all([(active, validate_rule(active.expression_json))], records, floor)
        if active and active.id != rv.id
        else []
    )

    def summarise(outs: list[tuple[Any, Any, Any, Outcome]]) -> dict[str, Any]:
        found = [o for *_, o in outs if o.is_finding]
        by_lga: Counter[str] = Counter()
        lga_of = {(r["subject_id"], r.get("period")): r.get("lga_code") for _, _, r, _ in outs}
        for o in found:
            by_lga[str(lga_of.get((o.subject_id, o.period)) or "unknown")] += 1
        return {
            "evaluated": len(outs),
            "findings": len(found),
            "data_holds": sum(o.data_hold for o in found),
            "suppressed": sum(1 for *_, o in outs if o.outcome == "suppressed"),
            "bands": dict(Counter(o.priority_band or "unscored" for o in found)),
            "by_lga": dict(by_lga),
        }

    cand_keys = {finding_key(o) for *_, o in cand_out if o.is_finding}
    base_keys = {finding_key(o) for *_, o in base_out if o.is_finding}
    report: dict[str, Any] = {
        "rule": f"{rv.rule_code}@{rv.version}",
        "compared_with": f"{active.rule_code}@{active.version}" if active and active.id != rv.id else None,
        "as_of": as_of.isoformat(),
        "periods": [period_from, period_to],
        "candidate": summarise(cand_out),
        "active": summarise(base_out) if base_out else None,
        "newly_flagged": sorted(cand_keys - base_keys)[:50],
        "no_longer_flagged": sorted(base_keys - cand_keys)[:50],
        "newly_flagged_count": len(cand_keys - base_keys),
        "no_longer_flagged_count": len(base_keys - cand_keys),
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": actor.actor_id,
    }
    rv.backtest_report = report
    db.flush()
    audit.record(
        db,
        actor,
        "rule.backtested",
        f"rule:{rv.rule_code}@{rv.version}",
        {
            "findings": report["candidate"]["findings"],
            "newly_flagged": report["newly_flagged_count"],
            "no_longer_flagged": report["no_longer_flagged_count"],
        },
    )
    return report
