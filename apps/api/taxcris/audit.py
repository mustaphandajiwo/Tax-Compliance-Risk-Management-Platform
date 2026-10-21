"""Tamper-evident audit trail (FR-09).

Each tenant has an append-only hash chain: ``event_hash = sha256(prev_hash || canonical(event))``.
The tenant row is locked while appending so the chain is strictly ordered. ``verify_chain``
recomputes every hash and reports the first break.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, Tenant
from .security import canonical_json, sha256_json


def _utc_iso(ts: datetime) -> str:
    # Some drivers return naive datetimes; stored values are always UTC.
    ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
    return ts.isoformat()


def _event_material(e: AuditEvent) -> dict[str, Any]:
    return {
        "tenant_id": str(e.tenant_id),
        "seq": e.seq,
        "timestamp": _utc_iso(e.timestamp),
        "actor_id": str(e.actor_id) if e.actor_id else None,
        "actor_role": e.actor_role,
        "action": e.action,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "outcome": e.outcome,
        "details": e.details,
        "before_hash": e.before_hash,
        "after_hash": e.after_hash,
    }


def _hash(prev_hash: str, material: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(material)).encode()).hexdigest()


def record(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: Any = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    before: Any = None,
    after: Any = None,
) -> AuditEvent:
    """Append an event within the caller's transaction. Never put raw sensitive values in ``details``."""
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update()).scalar_one()
    seq = tenant.audit_seq + 1
    event = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        seq=seq,
        timestamp=datetime.now(timezone.utc).replace(microsecond=0),
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        details=details or {},
        before_hash=sha256_json(before) if before is not None else None,
        after_hash=sha256_json(after) if after is not None else None,
        prev_hash=tenant.audit_head_hash,
    )
    event.event_hash = _hash(event.prev_hash, _event_material(event))
    tenant.audit_seq = seq
    tenant.audit_head_hash = event.event_hash
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    prev = "0" * 64
    count = 0
    for e in db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq)
    ).scalars():
        count += 1
        if e.seq != count:
            return {"valid": False, "events_checked": count, "first_invalid_seq": e.seq, "reason": "sequence gap"}
        if e.prev_hash != prev or _hash(prev, _event_material(e)) != e.event_hash:
            return {"valid": False, "events_checked": count, "first_invalid_seq": e.seq, "reason": "hash mismatch"}
        prev = e.event_hash
    head = db.get(Tenant, tenant_id)
    if head is not None and head.audit_head_hash != prev:
        return {"valid": False, "events_checked": count, "first_invalid_seq": None, "reason": "head mismatch (truncation)"}
    return {"valid": True, "events_checked": count, "first_invalid_seq": None, "reason": None, "head_hash": prev}
