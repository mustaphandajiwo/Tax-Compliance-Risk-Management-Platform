"""Finding review, overrides and state changes (FR-012/013)."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from risk_engine.scoring import priority_band, priority_index
from risk_engine.states import FINDING_TRANSITIONS, REVIEW_DECISIONS, TransitionError

from .. import audit
from ..errors import conflict, forbidden, unprocessable
from ..models import FindingEvent, RiskFinding
from ..security.auth import Principal


def check_version(f: RiskFinding | Any, expected: int | None) -> None:
    if expected is not None and expected != f.version:
        raise conflict(
            "The record changed since you loaded it; reload and retry",
            {"expected_version": expected, "current_version": f.version},
        )


def path_to(current: str, target: str) -> list[str]:
    """Shortest allowed sequence of states from current to target (exclusive of current)."""
    if current == target:
        return []
    seen = {current}
    q: deque[tuple[str, list[str]]] = deque([(current, [])])
    while q:
        state, path = q.popleft()
        for nxt in sorted(FINDING_TRANSITIONS.get(state, set())):
            if nxt in seen:
                continue
            if nxt == target:
                return [*path, nxt]
            seen.add(nxt)
            q.append((nxt, [*path, nxt]))
    raise TransitionError(f"finding cannot move from {current} to {target}")


def transition(
    db: Session,
    f: RiskFinding,
    target: str,
    actor_id: str,
    reason: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    for step in path_to(f.status, target):
        db.add(
            FindingEvent(
                tenant_id=f.tenant_id,
                finding_id=f.id,
                event_type="state_change",
                from_status=f.status,
                to_status=step,
                actor_id=actor_id,
                reason=reason,
                details=details or {},
            )
        )
        f.status = step


def snapshot(f: RiskFinding) -> dict[str, Any]:
    return {
        "status": f.status,
        "likelihood": f.likelihood,
        "consequence": f.consequence,
        "priority": f.priority,
        "data_hold": f.data_hold,
        "legal_hold": f.legal_hold,
        "disputed": f.disputed,
        "holds": list(f.holds),
    }


def review(
    db: Session, actor: Principal, f: RiskFinding, decision: str, reason: str, expected_version: int | None
) -> RiskFinding:
    check_version(f, expected_version)
    if decision not in REVIEW_DECISIONS:
        raise unprocessable(f"Unknown decision {decision}", {"allowed": sorted(REVIEW_DECISIONS)})
    if not reason.strip():
        raise unprocessable("A reason is required for every review decision")
    if f.superseded_by_id is not None and decision == "confirm":
        raise conflict("Finding is superseded by a newer rule version; review the current finding")
    before = snapshot(f)
    target = REVIEW_DECISIONS[decision]
    if decision == "confirm" and f.data_hold:
        raise conflict(
            "Data-hold findings cannot be confirmed as taxpayer risk; resolve the data issue first",
            {"holds": f.holds},
        )
    if decision in ("set_legal_hold", "clear_legal_hold") and not actor.can("risks:legal_hold"):
        raise forbidden("Only legal approvers or compliance managers set legal holds")
    if decision == "mark_disputed":
        f.disputed = True
        f.allowed_next_action = "internal_review_only"
    elif decision == "clear_disputed":
        f.disputed = False
    elif decision == "set_legal_hold":
        f.legal_hold = True
        f.holds = [*[h for h in f.holds if h != "officer_legal_hold"], "officer_legal_hold"]
        f.allowed_next_action = "internal_review_only"
    elif decision == "clear_legal_hold":
        f.holds = [h for h in f.holds if h != "officer_legal_hold"]
        f.legal_hold = "legal_hold" in f.holds
    if target is not None:
        transition(db, f, target, actor.actor_id, reason, {"decision": decision})
    db.add(
        FindingEvent(
            tenant_id=f.tenant_id,
            finding_id=f.id,
            event_type=f"review.{decision}",
            actor_id=actor.actor_id,
            reason=reason,
            details={"before": before},
        )
    )
    f.version += 1
    f.updated_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        actor,
        f"finding.review.{decision}",
        f"finding:{f.finding_ref}",
        {"reason": reason},
        before=before,
        after=snapshot(f),
    )
    return f


def override(
    db: Session,
    actor: Principal,
    f: RiskFinding,
    likelihood: int | None,
    consequence: int | None,
    reason: str,
    expected_version: int | None,
) -> RiskFinding:
    check_version(f, expected_version)
    if not reason.strip():
        raise unprocessable("An override needs a reason")
    if f.data_hold:
        raise conflict("Data-hold findings carry no score to override")
    for name, v in (("likelihood", likelihood), ("consequence", consequence)):
        if v is not None and not 1 <= v <= 5:
            raise unprocessable(f"{name} must be 1-5")
    previous = {
        "likelihood": f.likelihood,
        "consequence": f.consequence,
        "priority": f.priority,
        "priority_band": f.priority_band,
    }
    new_l = likelihood if likelihood is not None else f.likelihood
    new_c = consequence if consequence is not None else f.consequence
    f.likelihood, f.consequence = new_l, new_c
    f.priority = priority_index(new_l, new_c)
    f.priority_band = priority_band(f.priority)
    f.priority_note = None if f.priority is not None else "exposure_unknown"
    at = datetime.now(UTC).isoformat()
    f.override = {
        "likelihood": new_l,
        "consequence": new_c,
        "reason": reason,
        "actor": actor.actor_id,
        "at": at,
        "previous": previous,
    }
    f.version += 1
    db.add(
        FindingEvent(
            tenant_id=f.tenant_id,
            finding_id=f.id,
            event_type="override",
            actor_id=actor.actor_id,
            reason=reason,
            details={"previous": previous, "new": {"likelihood": new_l, "consequence": new_c}},
        )
    )
    db.flush()
    audit.record(
        db,
        actor,
        "finding.override",
        f"finding:{f.finding_ref}",
        {"reason": reason, "previous": previous, "new": {"likelihood": new_l, "consequence": new_c}},
        before=previous,
        after=f.override,
    )
    return f
