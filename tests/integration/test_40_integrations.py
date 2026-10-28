"""Collection-platform connector, signed webhooks and the JSON push API, against the simulated platform."""

from __future__ import annotations

import math
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.integration.conftest import World, token_for
from tools import mock_collection_platform as mock

pytestmark = pytest.mark.integration
TRANSPORT = httpx.MockTransport(mock.handler)
CODE = "COLLECTION-PLATFORM"


def _pull(world: World):  # type: ignore[no-untyped-def]
    from ngsirs_api.db import tenant_session
    from ngsirs_api.services import integrations

    with tenant_session(world.ngsirs) as db:
        run = integrations.run_pull(
            db, integrations.get_connector(db, CODE), "ngsirs_payment", trigger="manual", transport=TRANSPORT
        )
        return integrations.run_payload(run)


def test_pull_fails_safely_without_credentials(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NGSIRS_COLLECTION_API_KEY", raising=False)
    run = _pull(world)
    assert run["status"] == "failed" and "not configured" in run["error"] and run["batch_id"] is None
    monkeypatch.setenv("NGSIRS_COLLECTION_API_KEY", "wrong-key")
    run = _pull(world)
    assert run["status"] == "failed" and "HTTP 401" in run["error"]
    assert "wrong-key" not in run["error"]  # credentials never echoed


def test_pull_pages_filters_dedupes_validates_and_commits(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ngsirs_api.db import tenant_session
    from ngsirs_api.models import Connector, IngestBatch, Payment, SourceRecord

    monkeypatch.setenv("NGSIRS_COLLECTION_API_KEY", mock.API_KEY)
    run = _pull(world)
    total = len(mock.TRANSACTIONS)
    assert run["status"] == "succeeded", run
    assert run["records_received"] == total and run["pages"] == math.ceil(total / 25)
    assert run["records_filtered"] == 1  # BUSINESS_PREMISES is outside the PAYE pilot
    assert run["cursor_to"] == max(t["updated_at"] for t in mock.TRANSACTIONS)
    with tenant_session(world.ngsirs) as db:
        batch = db.get(IngestBatch, run["batch_id"])
        assert (
            batch.qa_status == "committed" and batch.coverage_from is None
        )  # incremental pull: no coverage claim
        assert batch.row_count == total - 1 - 1  # filtered + the superseded pre-reversal version
        bad = (
            db.execute(
                select(SourceRecord).where(
                    SourceRecord.batch_id == batch.id, SourceRecord.status == "quarantined"
                )
            )
            .scalars()
            .all()
        )
        assert [r.natural_id for r in bad] == ["CP-2026-09-BADP"] and "invalid_period" in bad[0].reason_codes
        reversed_ = db.execute(
            select(Payment).where(
                Payment.payment_reference == mock.TRANSACTIONS[3]["transaction_ref"], Payment.is_current
            )
        ).scalar_one()
        assert reversed_.reversal_status == "reversed"
        unallocated = db.execute(
            select(Payment).where(Payment.payment_reference == "CP-2026-09-UNAL1")
        ).scalar_one()
        assert unallocated.employer_id is None and unallocated.allocation_status == "unallocated"
        assert (
            db.execute(select(Payment).where(Payment.payment_reference == "CP-2026-09-BPL1")).first() is None
        )
        c = db.execute(select(Connector).where(Connector.code == CODE)).scalar_one()
        assert c.state["ngsirs_payment"]["cursor"] == run["cursor_to"] and c.last_status == "succeeded"

    again = _pull(world)
    assert (
        again["status"] == "no_new_data"
        and again["cursor_from"] == run["cursor_to"]
        and again["batch_id"] is None
    )


def test_connector_api_and_permissions(client: TestClient, auth: dict) -> None:
    listed = client.get("/api/v1/connectors", headers=auth["steward"]).json()
    c = next(x for x in listed if x["code"] == CODE)
    assert (
        c["source"] == "ngsirs_collection_platform"
        and "config" in c
        and "secret" not in str(c["config"]).lower()
    )
    detail = client.get(f"/api/v1/connectors/{CODE}", headers=auth["steward"]).json()
    assert detail["runs"] and {r["trigger"] for r in detail["runs"]} >= {"manual"}
    assert client.post(f"/api/v1/connectors/{CODE}/run", headers=auth["officer"]).status_code == 403
    assert client.get("/api/v1/connectors", headers=auth["officer"]).status_code == 403


def test_webhook_signature_replay_and_freshness(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NGSIRS_COLLECTION_WEBHOOK_SECRET", mock.WEBHOOK_SECRET)
    tx = {**mock.TRANSACTIONS[0], "transaction_ref": "CP-WH-0001", "updated_at": "2026-10-20T10:00:00+01:00"}
    url = f"/api/v1/connectors/{CODE}/webhook"
    body, headers = mock.signed_webhook([tx], "evt-0001")
    r = client.post(url, content=body, headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "committed", r.text
    assert client.post(url, content=body, headers=headers).json()["status"] == "duplicate"
    body2, headers2 = mock.signed_webhook([tx], "evt-0002", secret="not-the-secret")
    assert client.post(url, content=body2, headers=headers2).status_code == 401
    body3, headers3 = mock.signed_webhook([tx], "evt-0003", timestamp=int(time.time()) - 3600)
    r3 = client.post(url, content=body3, headers=headers3)
    assert r3.status_code == 401 and "window" in r3.json()["error"]["message"]
    tampered = body.replace(b"CP-WH-0001", b"CP-WH-9999")
    assert client.post(url, content=tampered, headers=headers).status_code == 401
    assert client.post(url, content=body, headers={"Content-Type": "application/json"}).status_code == 401
    assert client.post("/api/v1/connectors/NOPE/webhook", content=body, headers=headers).status_code == 404


def test_push_api_for_machine_clients(client: TestClient, auth: dict, world: World) -> None:
    svc = token_for(world.ngsirs, "NGSIRS", ["integration_client"], "etax-portal-client")
    record = {
        "payment_reference": "PUSH-0001",
        "employer_id": world.scenarios["clean"][0],
        "tax_type": "PAYE",
        "period": "2026-09",
        "paid_at": "2026-10-07T10:00:00+01:00",
        "amount": "150000.00",
        "reversal_status": "none",
        "settlement_status": "settled",
        "allocation_status": "allocated",
    }
    body = {"source": "ngsirs_treasury", "extracted_at": "2026-10-27T12:00:00+01:00", "records": [record]}
    url = "/api/v1/ingest/ngsirs_payment"
    r = client.post(url, headers={**svc, "Idempotency-Key": "push-1"}, json=body)
    assert r.status_code == 201 and r.json()["qa_status"] == "committed", r.text
    again = client.post(url, headers={**svc, "Idempotency-Key": "push-1"}, json=body)
    assert again.json()["id"] == r.json()["id"]
    assert (
        client.post(url, headers=svc, json={**body, "records": [{**record, "nickname": "x"}]}).status_code
        == 422
    )
    assert client.post(
        url, headers=svc, json={**body, "source": "external_business_licensing"}
    ).status_code in (403, 422)
    assert client.post("/api/v1/ingest/not_a_feed", headers=svc, json=body).status_code == 422
    assert client.post(url, headers=auth["officer"], json=body).status_code == 403
    assert client.get("/api/v1/risks", headers=svc).status_code == 403  # machine clients cannot read risks
