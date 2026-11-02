"""Database sessions bound to one tenant.

The tenant id is written into the transaction-local setting ``app.tenant_id``
at the start of every transaction, and Postgres row-level security filters on
it. Application code still filters by tenant (defence in depth), but a query
that forgets to cannot see another tenant's rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(s.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


@event.listens_for(Session, "after_begin")
def _bind_tenant(session: Session, transaction: object, connection: object) -> None:
    tid = session.info.get("tenant_id")
    if tid is not None:
        connection.exec_driver_sql(  # type: ignore[attr-defined]
            "SELECT set_config('app.tenant_id', %(t)s, true)", {"t": str(tid)}
        )


def new_session(tenant_id: uuid.UUID | str | None) -> Session:
    session = _factory()()
    session.info["tenant_id"] = str(tenant_id) if tenant_id else None
    return session


@contextmanager
def tenant_session(tenant_id: uuid.UUID | str) -> Iterator[Session]:
    session = new_session(tenant_id)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_tenant_id(code: str) -> uuid.UUID | None:
    with get_engine().connect() as conn:
        value = conn.execute(text("SELECT app_resolve_tenant(:c)"), {"c": code}).scalar()
    return uuid.UUID(str(value)) if value else None
