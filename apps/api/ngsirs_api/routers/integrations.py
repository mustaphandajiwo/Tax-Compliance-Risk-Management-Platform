"""Integration endpoints: connector management, signed webhooks and the JSON push API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from importer import FEEDS

from ..config import get_settings
from ..db import new_session, resolve_tenant_id
from ..errors import ApiError, unprocessable
from ..idempotency import run_once
from ..models import Connector, ConnectorRun
from ..security.auth import Principal, get_db, require
from ..services import imports, integrations

router = APIRouter(prefix="/api/v1", tags=["integrations"])


class PushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    extracted_at: datetime
    coverage_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    coverage_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    coverage_lga: str | None = None
    commit: bool = True
    records: list[dict[str, Any]] = Field(min_length=1, max_length=integrations.MAX_RECORDS)


@router.post("/ingest/{feed_type}", status_code=201)
def push(
    feed_type: str,
    body: PushRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("ingest:push")),
    db: Session = Depends(get_db),
) -> dict:
    """Push canonical records as JSON (e-tax portal, collection platform, employer payroll/ERP systems).

    Records use the canonical column names of the feed (GET /api/v1/imports/templates). They go through the
    same validation, quarantine, provenance and data-sharing checks as file imports.
    """
    if feed_type not in FEEDS:
        raise unprocessable(f"Unknown feed {feed_type}", {"known": list(FEEDS)})
    columns = {c.name for c in FEEDS[feed_type].columns}
    unknown = sorted({k for r in body.records for k in r} - columns)
    if unknown:
        raise unprocessable("Records contain fields that are not in the feed profile", unknown)
    rows = [{k: "" if v is None else str(v) for k, v in r.items()} for r in body.records]

    def do() -> dict:
        batch, created = integrations.ingest(
            db,
            principal,
            source_name=body.source,
            feed_type=feed_type,
            rows=rows,
            extracted_at=body.extracted_at,
            label=f"push-{feed_type}-{body.extracted_at:%Y%m%dT%H%M%S}",
            coverage=(body.coverage_from, body.coverage_to),
            coverage_lga=body.coverage_lga,
            commit=body.commit,
        )
        return {**imports.batch_payload(batch, body.source), "created": created}

    return run_once(db, principal, idempotency_key, f"POST /ingest/{feed_type}", body, do)  # type: ignore[no-any-return]


@router.get("/connectors")
def list_connectors(
    _: Principal = Depends(require("imports:read")), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        integrations.connector_payload(db, c)
        for c in db.execute(select(Connector).order_by(Connector.code)).scalars()
    ]


@router.get("/connectors/{code}")
def get_connector(
    code: str, _: Principal = Depends(require("imports:read")), db: Session = Depends(get_db)
) -> dict:
    c = integrations.get_connector(db, code)
    runs = db.execute(
        select(ConnectorRun)
        .where(ConnectorRun.connector_id == c.id)
        .order_by(ConnectorRun.started_at.desc())
        .limit(50)
    ).scalars()
    return {**integrations.connector_payload(db, c), "runs": [integrations.run_payload(r) for r in runs]}


@router.post("/connectors/{code}/run")
def run_connector(
    code: str,
    feed_type: str = "ngsirs_payment",
    _: Principal = Depends(require("connectors:run")),
    db: Session = Depends(get_db),
) -> dict:
    c = integrations.get_connector(db, code)
    return integrations.run_payload(integrations.run_pull(db, c, feed_type, trigger="manual"))


@router.post("/connectors/{code}/webhook", include_in_schema=True)
async def webhook(code: str, request: Request, x_signature: str | None = Header(default=None)) -> dict:
    """Receive a push from the source system. Authenticated by HMAC signature, not a bearer token."""
    body = await request.body()
    if len(body) > 10 * 1024 * 1024:
        raise ApiError(413, "too_large", "Webhook body exceeds 10 MB")
    tid = resolve_tenant_id(get_settings().default_tenant_code)
    if tid is None:
        raise ApiError(404, "not_found", "Connector not found")
    db = new_session(tid)
    try:
        c = db.execute(select(Connector).where(Connector.code == code)).scalar_one_or_none()
        if c is None:
            raise ApiError(404, "not_found", "Connector not found")
        result = integrations.receive_webhook(db, c, body, x_signature)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
