"""Idempotency keys for mutations (Tech Spec section 11).

A client retries a POST with the same ``Idempotency-Key`` and receives the
original response. Reusing a key with a different body is a 409.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.hashing import sha256_hex

from .errors import conflict
from .models import IdempotencyRecord
from .security.auth import Principal


def run_once(
    db: Session, principal: Principal, key: str | None, endpoint: str, body: Any, fn: Callable[[], Any]
) -> Any:
    if not key:
        return fn()
    req_hash = sha256_hex(jsonable_encoder(body))
    existing = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == principal.actor_id, IdempotencyRecord.key == key
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.endpoint != endpoint or existing.request_hash != req_hash:
            raise conflict("Idempotency-Key was already used with a different request")
        return existing.response
    result = jsonable_encoder(fn())
    db.add(
        IdempotencyRecord(
            tenant_id=principal.tenant_id,
            actor_id=principal.actor_id,
            key=key,
            endpoint=endpoint,
            request_hash=req_hash,
            status_code=200,
            response=result,
        )
    )
    db.flush()
    return result
