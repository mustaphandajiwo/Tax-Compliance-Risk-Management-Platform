"""Tamper-evident audit chain.

Each event stores the previous event's hash and its own hash over the
canonical event body, per tenant. Rows are append-only (database trigger and
revoked privileges). ``verify_chain`` recomputes every hash so any edit,
deletion or reordering made by someone who bypassed those controls is detected.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from risk_engine.hashing import canonical_json, sha256_hex

from .errors import current_trace_id
from .models import AuditEvent
from .security.auth import Principal

GENESIS = "0" * 64


def _body(e: AuditEvent) -> dict[str, Any]:
    return {
        "tenant_id": str(e.tenant_id),
        "seq": e.seq,
        "actor_id": e.actor_id,
        "actor_roles": list(e.actor_roles),
        "event_type": e.event_type,
        "subject_ref": e.subject_ref,
        "purpose": e.purpose,
        "before_hash": e.before_hash,
        "after_hash": e.after_hash,
        "details": e.details,
        "trace_id": e.trace_id,
        "occurred_at": e.occurred_at.astimezone(UTC).isoformat(),
    }


def record(
    db: Session,
    actor: Principal | str,
    event_type: str,
    subject_ref: str | None,
    details: dict[str, Any] | None = None,
    *,
    before: Any = None,
    after: Any = None,
    purpose: str | None = None,
    tenant_id: uuid.UUID | None = None,
) -> AuditEvent:
    if isinstance(actor, Principal):
        actor_id, roles, tid = actor.actor_id, list(actor.roles), actor.tenant_id
    else:
        actor_id, roles, tid = actor, ["system"], tenant_id  # type: ignore[assignment]
    if tid is None:
        raise ValueError("tenant_id required for system audit events")
    # Serialise chain appends per tenant.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:t, 7))"), {"t": str(tid)})
    last = db.execute(
        select(AuditEvent.seq, AuditEvent.event_hash)
        .where(AuditEvent.tenant_id == tid)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    ).first()
    seq = (last.seq + 1) if last else 1
    prev = last.event_hash if last else GENESIS
    event = AuditEvent(
        tenant_id=tid,
        seq=seq,
        actor_id=actor_id,
        actor_roles=roles,
        event_type=event_type,
        subject_ref=subject_ref,
        purpose=purpose,
        before_hash=sha256_hex(before) if before is not None else None,
        after_hash=sha256_hex(after) if after is not None else None,
        details=json.loads(canonical_json(details or {})),
        trace_id=current_trace_id(),
        occurred_at=datetime.now(UTC),
        prev_hash=prev,
    )
    event.event_hash = sha256_hex({"prev": prev, "body": _body(event)})
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    prev = GENESIS
    expected_seq = 1
    count = 0
    for e in db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq)
    ).scalars():
        count += 1
        if e.seq != expected_seq:
            return {"valid": False, "events": count, "broken_at_seq": e.seq, "reason": "sequence gap"}
        if e.prev_hash != prev:
            return {"valid": False, "events": count, "broken_at_seq": e.seq, "reason": "prev_hash mismatch"}
        if sha256_hex({"prev": prev, "body": _body(e)}) != e.event_hash:
            return {"valid": False, "events": count, "broken_at_seq": e.seq, "reason": "event_hash mismatch"}
        prev = e.event_hash
        expected_seq += 1
    return {"valid": True, "events": count, "head_hash": prev}
