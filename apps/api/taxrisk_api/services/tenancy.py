"""The current tenant's configuration (from its jurisdiction pack), read through row-level security."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Tenant

DEFAULT_TZ = "Africa/Lagos"


def tenant_of(db: Session) -> Tenant | None:
    # The session is bound to one tenant and the tenant table's policy shows only that row.
    return db.execute(select(Tenant)).scalars().first()


def settings_of(db: Session) -> dict[str, Any]:
    t = tenant_of(db)
    return dict((t.settings if t else {}) or {})


def tz_of(db: Session) -> tzinfo:
    return ZoneInfo(settings_of(db).get("timezone") or DEFAULT_TZ)


def local_label(dt: datetime, tz: tzinfo) -> str:
    local = dt.astimezone(tz)
    return f"{local:%Y-%m-%d %H:%M} {local.tzname()}"
