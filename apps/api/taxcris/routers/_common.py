import uuid
from typing import Any, TypeVar

from fastapi import HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from .. import audit
from ..deps import Principal

M = TypeVar("M")


def get_scoped(db: Session, model: type[M], obj_id: uuid.UUID, principal: Principal) -> M:
    """Fetch a tenant-scoped row. Rows from other tenants are indistinguishable from missing ones."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "tenant_id", None) != principal.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def paginate(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list[Any], int]:
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    return rows, total


def log(db: Session, principal: Principal, action: str, resource_type: str, resource_id=None, **details) -> None:
    audit.record(
        db, tenant_id=principal.tenant_id, actor_id=principal.user_id, actor_role=principal.role, action=action,
        resource_type=resource_type, resource_id=resource_id, details=details,
    )


Limit = Query(50, ge=1, le=500)
Offset = Query(0, ge=0)
