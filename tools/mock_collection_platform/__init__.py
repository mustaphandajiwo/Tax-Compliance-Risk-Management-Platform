"""Simulated revenue collection platform (SYNTHETIC) for developing and testing the connector.

Behaves like a typical Nigerian state revenue collection gateway:

    GET /v1/transactions?updated_since=<ISO>&page=<n>&page_size=<n>     header X-API-Key: <key>
    -> {"data": [transaction, ...], "page": n, "next_page": n+1 | null}

    transaction = {
      "transaction_ref": "CP-...", "revenue_code": "PAYE" | "BUSINESS_PREMISES" | ...,
      "payer": {"employer_id": "NGS-DEMO-EMP-0001", "name": "..."},
      "period": "2026-09", "amount": "123000.00", "paid_at": ISO, "status": "SUCCESSFUL" | "PENDING" | "REVERSED",
      "allocation": "ALLOCATED" | "UNALLOCATED", "channel": "bank_branch" | "card" | "transfer", "updated_at": ISO
    }

It can also push webhooks signed with ``X-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>``.

``handler`` is a pure function usable with ``httpx.MockTransport`` (tests); ``app`` serves it over HTTP
(``uvicorn tools.mock_collection_platform:app --port 8100``) for the live demo.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

API_KEY = "demo-collection-platform-key"  # noqa: S105 - synthetic demo credential
WEBHOOK_SECRET = "demo-collection-webhook-secret"  # noqa: S105 - synthetic demo credential
WAT = timezone(timedelta(hours=1))
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ngsirs"


def _transactions() -> list[dict[str, Any]]:
    """September 2026 PAYE remittances for active employers, plus the awkward cases a gateway produces."""
    out: list[dict[str, Any]] = []
    with (FIXTURES / "employers.csv").open() as fh:
        employers = [r for r in csv.DictReader(fh) if r["status"] == "active"]
    base = datetime(2026, 10, 6, 9, 0, tzinfo=WAT)
    for i, e in enumerate(employers[:60]):
        n = int(e["source_employer_id"].rsplit("-", 1)[1])
        paid = base + timedelta(hours=i * 3)
        out.append(
            {
                "transaction_ref": f"CP-2026-09-{n:04d}",
                "revenue_code": "PAYE",
                "payer": {"employer_id": e["source_employer_id"], "name": e["employer_name"]},
                "period": "2026-09",
                "amount": f"{100000 + n * 1500}.00",
                "paid_at": paid.isoformat(),
                "status": "SUCCESSFUL",
                "allocation": "ALLOCATED",
                "channel": ["bank_branch", "card", "transfer"][i % 3],
                "updated_at": (paid + timedelta(minutes=5)).isoformat(),
            }
        )
    late = base + timedelta(days=1)
    out += [
        # The bank reverses an earlier settled payment: same reference, new status, later updated_at.
        {**out[3], "status": "REVERSED", "updated_at": late.isoformat()},
        # Received but not matched to a payer: becomes a PAY-005 reconciliation item, never non-payment.
        {
            "transaction_ref": "CP-2026-09-UNAL1",
            "revenue_code": "PAYE",
            "payer": {"employer_id": None, "name": "?"},
            "period": "2026-09",
            "amount": "87500.00",
            "paid_at": late.isoformat(),
            "status": "SUCCESSFUL",
            "allocation": "UNALLOCATED",
            "channel": "transfer",
            "updated_at": (late + timedelta(minutes=1)).isoformat(),
        },
        # Not PAYE: outside the pilot's legal scope, filtered out by the connector.
        {
            "transaction_ref": "CP-2026-09-BPL1",
            "revenue_code": "BUSINESS_PREMISES",
            "payer": {"employer_id": out[0]["payer"]["employer_id"], "name": "x"},
            "period": "2026",
            "amount": "25000.00",
            "paid_at": late.isoformat(),
            "status": "SUCCESSFUL",
            "allocation": "ALLOCATED",
            "channel": "card",
            "updated_at": (late + timedelta(minutes=2)).isoformat(),
        },
        # A period the gateway captured wrongly: quarantined at import (DAT-002), never guessed.
        {
            **out[5],
            "transaction_ref": "CP-2026-09-BADP",
            "period": "2026-9",
            "updated_at": (late + timedelta(minutes=3)).isoformat(),
        },
    ]
    return sorted(out, key=lambda t: t["updated_at"])


TRANSACTIONS = _transactions()


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path != "/v1/transactions":
        return httpx.Response(404, json={"error": "not found"})
    if request.headers.get("X-API-Key") != API_KEY:
        return httpx.Response(401, json={"error": "invalid API key"})
    q = request.url.params
    since = q.get("updated_since")
    page = int(q.get("page", "1"))
    size = min(int(q.get("page_size", "25")), 100)
    rows = [
        t
        for t in TRANSACTIONS
        if not since or datetime.fromisoformat(t["updated_at"]) > datetime.fromisoformat(since)
    ]
    chunk = rows[(page - 1) * size : page * size]
    more = page * size < len(rows)
    return httpx.Response(200, json={"data": chunk, "page": page, "next_page": page + 1 if more else None})


def signed_webhook(
    transactions: list[dict[str, Any]],
    event_id: str,
    secret: str = WEBHOOK_SECRET,
    timestamp: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "event_id": event_id,
            "event_type": "payment.settled",
            "occurred_at": datetime.now(WAT).isoformat(),
            "data": transactions,
        }
    ).encode()
    t = str(timestamp if timestamp is not None else int(time.time()))
    sig = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"X-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def _asgi_app() -> FastAPI:
    api = FastAPI(title="Mock revenue collection platform (SYNTHETIC)")

    @api.get("/v1/transactions")
    def transactions(request: Request) -> Response:
        r = handler(httpx.Request("GET", str(request.url), headers=dict(request.headers)))
        return Response(r.content, status_code=r.status_code, media_type="application/json")

    return api


app = _asgi_app()
