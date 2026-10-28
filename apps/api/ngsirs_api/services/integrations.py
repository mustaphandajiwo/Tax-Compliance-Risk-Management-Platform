"""System integrations: scheduled pull connectors, signed webhooks and a JSON push API.

Every route into the platform ends in the same place: the records are mapped to a canonical feed, written
as a provenance batch (encrypted original, signed manifest, row-level validation and quarantine) and
committed through ``imports``. Nothing an integration sends can bypass validation, the data-sharing basis
check, quarantine or the audit trail.

Mapping is configuration, not code: each connector says where records live in the response, how pages and
cursors work, and how source fields (with value maps for status codes) become canonical columns. Wiring up
a different collection platform means writing that mapping, not a new adapter.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from importer import FEEDS

from .. import audit
from ..config import get_settings
from ..errors import ApiError, conflict, forbidden, not_found, unprocessable
from ..models import Connector, ConnectorEvent, ConnectorRun, DataSource
from ..security.auth import Principal
from . import imports
from .legal import next_period, period_bounds

MAX_RECORDS = 50_000


# --- configuration schema ---------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldRule(_Strict):
    source: str | None = Field(default=None, alias="from")
    const: str | None = None
    value_map: dict[str, str] = {}
    default: str | None = None


class RecordFilter(_Strict):
    field: str
    in_: list[str] = Field(alias="in")


class Coverage(_Strict):
    """Claim a period complete once it has been closed for ``settle_days`` (system-of-record sources only)."""

    start: str = Field(pattern=r"^\d{4}-\d{2}$")
    settle_days: int = Field(ge=1, le=120)


class FeedConfig(_Strict):
    path: str = Field(pattern=r"^/")
    records_path: str = "data"
    next_page_path: str | None = "next_page"
    page_param: str | None = "page"
    page_size_param: str | None = "page_size"
    page_size: int = Field(default=100, ge=1, le=1000)
    max_pages: int = Field(default=200, ge=1, le=5000)
    cursor_param: str | None = None
    cursor_field: str | None = None
    dedupe_key: str | None = None
    filter: RecordFilter | None = None
    mapping: dict[str, FieldRule]
    coverage: Coverage | None = None


class WebhookConfig(_Strict):
    feed_type: str
    records_path: str = "data"
    tolerance_seconds: int = Field(default=300, ge=30, le=3600)


class ConnectorConfig(_Strict):
    feeds: dict[str, FeedConfig] = {}
    webhook: WebhookConfig | None = None
    api_key_header: str = "X-API-Key"
    token_url: str | None = None
    client_id: str | None = None
    scope: str | None = None
    timeout_seconds: float = Field(default=30, ge=1, le=300)


def parse_config(raw: dict[str, Any]) -> ConnectorConfig:
    try:
        cfg = ConnectorConfig.model_validate(raw)
    except ValidationError as exc:
        raise unprocessable("Invalid connector configuration", [e["msg"] for e in exc.errors()]) from None
    for feed, fc in cfg.feeds.items():
        if feed not in FEEDS:
            raise unprocessable(f"Unknown feed {feed}")
        unknown = set(fc.mapping) - {c.name for c in FEEDS[feed].columns}
        if unknown:
            raise unprocessable(f"Mapping for {feed} targets unknown columns", sorted(unknown))
    return cfg


# --- record handling ---------------------------------------------------------------------------


def dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def map_record(record: dict[str, Any], mapping: dict[str, FieldRule]) -> dict[str, str]:
    out: dict[str, str] = {}
    for column, rule in mapping.items():
        if rule.const is not None:
            out[column] = rule.const
            continue
        value = dig(record, rule.source)
        text = "" if value is None else str(value)
        if text in rule.value_map:
            text = rule.value_map[text]
        elif rule.default is not None and (rule.value_map or not text):
            text = rule.default
        out[column] = text
    return out


def to_csv(feed_type: str, rows: list[dict[str, str]]) -> bytes:
    columns = [c.name for c in FEEDS[feed_type].columns]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in columns})
    return buf.getvalue().encode()


def prepare(records: list[dict[str, Any]], fc: FeedConfig) -> tuple[list[dict[str, str]], int]:
    """Filter, de-duplicate (latest version wins) and map raw source records."""
    kept = records
    if fc.filter is not None:
        kept = [r for r in kept if str(dig(r, fc.filter.field)) in fc.filter.in_]
    filtered = len(records) - len(kept)
    if fc.dedupe_key:
        latest: dict[str, dict[str, Any]] = {}
        for r in kept:
            key = str(dig(r, fc.dedupe_key))
            if key not in latest or str(dig(r, fc.cursor_field) or "") >= str(
                dig(latest[key], fc.cursor_field) or ""
            ):
                latest[key] = r
        kept = list(latest.values())
    return [map_record(r, fc.mapping) for r in kept], filtered


def closed_periods(cov: Coverage | None, now: datetime) -> tuple[str | None, str | None]:
    if cov is None:
        return None, None
    last = None
    p = cov.start
    while True:
        _, end = period_bounds(p)
        if datetime.combine(end, datetime.min.time(), tzinfo=UTC) + timedelta(days=cov.settle_days + 1) > now:
            break
        last = p
        p = next_period(p)
    return (cov.start, last) if last else (None, None)


def ingest(
    db: Session,
    actor: Principal,
    *,
    source_name: str,
    feed_type: str,
    rows: list[dict[str, str]],
    extracted_at: datetime,
    label: str,
    coverage: tuple[str | None, str | None] = (None, None),
    coverage_lga: str | None = None,
    commit: bool = True,
) -> tuple[Any, bool]:
    if len(rows) > MAX_RECORDS:
        raise unprocessable(f"At most {MAX_RECORDS} records per submission")
    batch, created = imports.create_batch(
        db,
        actor,
        source_name=source_name,
        feed_type=feed_type,
        file_name=f"{label}.csv",
        content=to_csv(feed_type, rows),
        extracted_at=extracted_at,
        coverage_from=coverage[0],
        coverage_to=coverage[1],
        coverage_lga=coverage_lga,
    )
    if created and commit and batch.qa_status == "validated":
        imports.commit_batch(db, actor, batch.id)
    return batch, created


def connector_principal(c: Connector) -> Principal:
    return Principal(
        sub=f"connector|{c.code}",
        username=f"connector:{c.code}",
        display_name=c.name,
        tenant_id=c.tenant_id,
        tenant_code=get_settings().default_tenant_code,
        roles=("data_steward",),
        purposes=("data_quality",),
        kind="service",
    )


def _source_name(db: Session, c: Connector) -> str:
    source = db.get(DataSource, c.source_id)
    if source is None:
        raise not_found("Data source")
    return source.source_name


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise unprocessable("Connector base_url must be an absolute http(s) URL")
    if parsed.scheme != "https" and get_settings().environment in ("staging", "production"):
        raise forbidden("Connectors must use HTTPS outside demo and test environments")


def _secret(env_name: str | None, what: str) -> str:
    value = os.environ.get(env_name or "")
    if not value:
        raise conflict(f"{what} is not configured (environment variable {env_name or '-'} is empty)")
    return value


def _auth_headers(c: Connector, cfg: ConnectorConfig, client: httpx.Client) -> dict[str, str]:
    if c.auth_type == "none":
        return {}
    secret = _secret(c.secret_env, "Connector credential")
    if c.auth_type == "api_key":
        return {cfg.api_key_header: secret}
    if c.auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if c.auth_type == "oauth2_client_credentials":
        if not cfg.token_url or not cfg.client_id:
            raise conflict("OAuth2 connector needs token_url and client_id")
        r = client.post(
            cfg.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": cfg.client_id,
                "client_secret": secret,
                **({"scope": cfg.scope} if cfg.scope else {}),
            },
        )
        if r.status_code != 200:
            raise ApiError(502, "upstream_auth_failed", f"Token endpoint returned {r.status_code}")
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    raise conflict(f"Unsupported auth type {c.auth_type}")


# --- pull --------------------------------------------------------------------------------------


def run_pull(
    db: Session, c: Connector, feed_type: str, *, trigger: str, transport: httpx.BaseTransport | None = None
) -> ConnectorRun:
    if not c.enabled:
        raise conflict(f"Connector {c.code} is disabled")
    if "pull" not in c.mode:
        raise conflict(f"Connector {c.code} does not pull")
    cfg = parse_config(c.config)
    fc = cfg.feeds.get(feed_type)
    if fc is None:
        raise unprocessable(f"Connector {c.code} has no {feed_type} feed")
    _check_url(c.base_url or "")
    state = dict(c.state or {})
    cursor = (state.get(feed_type) or {}).get("cursor")
    run = ConnectorRun(
        tenant_id=c.tenant_id,
        connector_id=c.id,
        trigger=trigger,
        feed_type=feed_type,
        status="running",
        cursor_from=cursor,
    )
    db.add(run)
    db.flush()
    actor = connector_principal(c)
    try:
        with db.begin_nested():
            with httpx.Client(
                base_url=c.base_url or "", timeout=cfg.timeout_seconds, transport=transport
            ) as client:
                headers = _auth_headers(c, cfg, client)
                records: list[dict[str, Any]] = []
                page = 1
                while True:
                    params: dict[str, Any] = {}
                    if fc.cursor_param and cursor:
                        params[fc.cursor_param] = cursor
                    if fc.page_param:
                        params[fc.page_param] = page
                    if fc.page_size_param:
                        params[fc.page_size_param] = fc.page_size
                    r = client.get(fc.path, params=params, headers=headers)
                    if r.status_code != 200:
                        raise ApiError(
                            502, "upstream_error", f"{c.code} returned HTTP {r.status_code} on page {page}"
                        )
                    body = r.json()
                    chunk = dig(body, fc.records_path) or []
                    if not isinstance(chunk, list):
                        raise ApiError(502, "upstream_error", f"{c.code}: '{fc.records_path}' is not a list")
                    records.extend(chunk)
                    run.pages = page
                    nxt = dig(body, fc.next_page_path) if fc.next_page_path else None
                    if not chunk or not nxt or not fc.page_param:
                        break
                    page = int(nxt)
                    if page > fc.max_pages:
                        raise ApiError(502, "upstream_error", f"{c.code}: more than {fc.max_pages} pages")
            run.records_received = len(records)
            rows, run.records_filtered = prepare(records, fc)
            new_cursor = (
                max(
                    (str(dig(r, fc.cursor_field)) for r in records if dig(r, fc.cursor_field)), default=cursor
                )
                if fc.cursor_field
                else None
            )
            now = datetime.now(UTC)
            if rows:
                batch, _ = ingest(
                    db,
                    actor,
                    source_name=_source_name(db, c),
                    feed_type=feed_type,
                    rows=rows,
                    extracted_at=now,
                    label=f"{c.code}-{feed_type}-{now:%Y%m%dT%H%M%S}",
                    coverage=closed_periods(fc.coverage, now),
                )
                run.batch_id = batch.id
                run.status = "succeeded" if batch.qa_status == "committed" else batch.qa_status
            else:
                run.status = "no_new_data"
            run.cursor_to = new_cursor
            state[feed_type] = {
                "cursor": new_cursor,
                "last_batch": str(run.batch_id) if run.batch_id else None,
                "last_success_at": now.isoformat(),
            }
            c.state = state
    except ApiError as exc:
        run.status, run.error = "failed", exc.message
    except httpx.HTTPError as exc:
        run.status, run.error = "failed", f"{type(exc).__name__}: could not reach {c.code}"
    run.finished_at = datetime.now(UTC)
    c.last_run_at, c.last_status = run.finished_at, run.status
    db.flush()
    audit.record(
        db,
        actor,
        "connector.pull",
        f"connector:{c.code}",
        {
            "feed_type": feed_type,
            "status": run.status,
            "records": run.records_received,
            "filtered": run.records_filtered,
            "batch": str(run.batch_id) if run.batch_id else None,
            "cursor_to": run.cursor_to,
            "error": run.error,
            "trigger": trigger,
        },
    )
    return run


def due_connectors(db: Session) -> list[Connector]:
    now = datetime.now(UTC)
    return [
        c
        for c in db.execute(select(Connector).where(Connector.enabled)).scalars()
        if "pull" in c.mode
        and (c.last_run_at is None or c.last_run_at + timedelta(minutes=c.schedule_minutes) <= now)
    ]


# --- webhook -------------------------------------------------------------------------------------


def verify_signature(
    secret: str, header: str | None, body: bytes, tolerance: int, now: float | None = None
) -> None:
    if not header:
        raise ApiError(401, "invalid_signature", "Missing X-Signature header")
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts, given = int(parts["t"]), parts["v1"]
    except (ValueError, KeyError):
        raise ApiError(401, "invalid_signature", "Malformed X-Signature header") from None
    if abs((now or time.time()) - ts) > tolerance:
        raise ApiError(401, "invalid_signature", "Signature timestamp outside the allowed window")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, given):
        raise ApiError(401, "invalid_signature", "Signature does not match")


def receive_webhook(db: Session, c: Connector, body: bytes, signature: str | None) -> dict[str, Any]:
    if not c.enabled or "webhook" not in c.mode:
        raise ApiError(404, "not_found", "Connector not found")
    cfg = parse_config(c.config)
    if cfg.webhook is None or cfg.webhook.feed_type not in cfg.feeds:
        raise conflict(f"Connector {c.code} has no webhook feed configured")
    verify_signature(
        _secret(c.webhook_secret_env, "Webhook secret"), signature, body, cfg.webhook.tolerance_seconds
    )
    try:
        payload = json.loads(body)
    except ValueError:
        raise unprocessable("Webhook body is not JSON") from None
    event_id = str(payload.get("event_id") or "")
    if not event_id:
        raise unprocessable("Webhook payload needs an event_id")
    if db.execute(
        select(ConnectorEvent).where(ConnectorEvent.connector_id == c.id, ConnectorEvent.event_id == event_id)
    ).scalar_one_or_none():
        return {"status": "duplicate", "event_id": event_id}
    records = dig(payload, cfg.webhook.records_path) or []
    if not isinstance(records, list):
        raise unprocessable(f"'{cfg.webhook.records_path}' is not a list")
    fc = cfg.feeds[cfg.webhook.feed_type]
    rows, filtered = prepare(records, fc)
    actor = connector_principal(c)
    batch_id = None
    status = "no_records"
    if rows:
        batch, _ = ingest(
            db,
            actor,
            source_name=_source_name(db, c),
            feed_type=cfg.webhook.feed_type,
            rows=rows,
            extracted_at=datetime.now(UTC),
            label=f"{c.code}-webhook-{event_id}",
        )
        batch_id, status = batch.id, batch.qa_status
    db.add(ConnectorEvent(tenant_id=c.tenant_id, connector_id=c.id, event_id=event_id, batch_id=batch_id))
    db.add(
        ConnectorRun(
            tenant_id=c.tenant_id,
            connector_id=c.id,
            trigger="webhook",
            feed_type=cfg.webhook.feed_type,
            status="succeeded" if status == "committed" else status,
            records_received=len(records),
            records_filtered=filtered,
            batch_id=batch_id,
            finished_at=datetime.now(UTC),
            cursor_to=event_id,
        )
    )
    db.flush()
    audit.record(
        db,
        actor,
        "connector.webhook",
        f"connector:{c.code}",
        {"event_id": event_id, "records": len(records), "filtered": filtered, "status": status},
    )
    return {
        "status": status,
        "event_id": event_id,
        "batch_id": str(batch_id) if batch_id else None,
        "records": len(records),
        "filtered": filtered,
    }


def get_connector(db: Session, code: str) -> Connector:
    c = db.execute(select(Connector).where(Connector.code == code)).scalar_one_or_none()
    if c is None:
        raise not_found("Connector")
    return c


def connector_payload(db: Session, c: Connector) -> dict[str, Any]:
    cfg = c.config or {}
    return {
        "id": str(c.id),
        "code": c.code,
        "name": c.name,
        "source": _source_name(db, c),
        "mode": c.mode,
        "base_url": c.base_url,
        "auth_type": c.auth_type,
        "secret_configured": bool(os.environ.get(c.secret_env or "")),
        "webhook_secret_configured": bool(os.environ.get(c.webhook_secret_env or "")),
        "feeds": sorted((cfg.get("feeds") or {}).keys()),
        "webhook_feed": (cfg.get("webhook") or {}).get("feed_type"),
        "schedule_minutes": c.schedule_minutes,
        "enabled": c.enabled,
        "state": c.state or {},
        "last_run_at": c.last_run_at.isoformat() if c.last_run_at else None,
        "last_status": c.last_status,
        "config": cfg,
    }


def run_payload(r: ConnectorRun) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "trigger": r.trigger,
        "feed_type": r.feed_type,
        "status": r.status,
        "cursor_from": r.cursor_from,
        "cursor_to": r.cursor_to,
        "pages": r.pages,
        "records_received": r.records_received,
        "records_filtered": r.records_filtered,
        "batch_id": str(r.batch_id) if r.batch_id else None,
        "error": r.error,
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


# --- seed ----------------------------------------------------------------------------------------

COLLECTION_PLATFORM_CONFIG: dict[str, Any] = {
    "api_key_header": "X-API-Key",
    "feeds": {
        "ngsirs_payment": {
            "path": "/v1/transactions",
            "records_path": "data",
            "next_page_path": "next_page",
            "page_param": "page",
            "page_size_param": "page_size",
            "page_size": 25,
            "cursor_param": "updated_since",
            "cursor_field": "updated_at",
            "dedupe_key": "transaction_ref",
            "filter": {"field": "revenue_code", "in": ["PAYE"]},
            "mapping": {
                "payment_reference": {"from": "transaction_ref"},
                "employer_id": {"from": "payer.employer_id"},
                "tax_type": {"from": "revenue_code"},
                "period": {"from": "period"},
                "paid_at": {"from": "paid_at"},
                "amount": {"from": "amount"},
                "reversal_status": {
                    "from": "status",
                    "value_map": {"REVERSED": "reversed"},
                    "default": "none",
                },
                "settlement_status": {
                    "from": "status",
                    "value_map": {"SUCCESSFUL": "settled", "PENDING": "pending", "REVERSED": "settled"},
                },
                "allocation_status": {
                    "from": "allocation",
                    "value_map": {"ALLOCATED": "allocated", "UNALLOCATED": "unallocated"},
                },
                "bank_delay_dispute": {"const": "false"},
                "credit_adjustment": {"const": "0.00"},
            },
        }
    },
    "webhook": {"feed_type": "ngsirs_payment", "records_path": "data", "tolerance_seconds": 300},
}


def seed_collection_platform(db: Session, tenant_id: uuid.UUID, base_url: str) -> Connector:
    """SYNTHETIC demo connector to the simulated collection platform (tools/mock_collection_platform)."""
    existing = db.execute(
        select(Connector).where(Connector.code == "COLLECTION-PLATFORM")
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    source = db.execute(
        select(DataSource).where(DataSource.source_name == "ngsirs_collection_platform")
    ).scalar_one_or_none()
    if source is None:
        source = DataSource(
            tenant_id=tenant_id,
            source_name="ngsirs_collection_platform",
            feed_types=["ngsirs_payment"],
            system_of_record=True,
            owner="NGSIRS revenue collection platform (vendor to be confirmed)",
            data_sharing_basis="Internal NGSIRS system of record (SYNTHETIC demo connection)",
            permitted_purpose="PAYE compliance risk management",
            freshness_sla_days=2,
        )
        db.add(source)
        db.flush()
    parse_config(COLLECTION_PLATFORM_CONFIG)
    c = Connector(
        tenant_id=tenant_id,
        code="COLLECTION-PLATFORM",
        name="NGSIRS revenue collection platform",
        source_id=source.id,
        mode="pull_and_webhook",
        base_url=base_url,
        auth_type="api_key",
        secret_env="NGSIRS_COLLECTION_API_KEY",  # noqa: S106 - env var name, not a secret
        webhook_secret_env="NGSIRS_COLLECTION_WEBHOOK_SECRET",  # noqa: S106 - env var name, not a secret
        config=COLLECTION_PLATFORM_CONFIG,
        state={},
        schedule_minutes=15,
        enabled=True,
    )
    db.add(c)
    db.flush()
    audit.record(
        db,
        "system:seed",
        "connector.created",
        f"connector:{c.code}",
        {"base_url": base_url},
        tenant_id=tenant_id,
    )
    return c
