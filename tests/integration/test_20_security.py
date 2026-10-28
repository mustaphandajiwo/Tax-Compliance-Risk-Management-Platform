"""Tenant isolation (defence in depth), authentication, authorisation and tamper evidence."""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from tests.conftest import ADMIN_URL, TEST_DB
from tests.integration.conftest import World, findings, token_for

pytestmark = pytest.mark.integration


# --- tenant isolation -------------------------------------------------------------------------


def test_rls_enabled_and_forced_on_every_tenant_table(world: World) -> None:
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
    with psycopg.connect(url) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.columns WHERE column_name='tenant_id' "
                "AND table_schema='public'"
            )
        }
        flags = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relkind='r'"
            )
        }
        policies = {r[0] for r in conn.execute("SELECT tablename FROM pg_policies WHERE schemaname='public'")}
        bypass = conn.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname='ngsirs_app'").fetchone()[0]
    assert tables, "expected tenant tables"
    missing = sorted(t for t in tables if t not in policies or flags[t] != (True, True))
    assert missing == [], f"tables without forced RLS: {missing}"
    assert bypass is False


def test_database_session_cannot_see_other_tenant_rows(world: World) -> None:
    from ngsirs_api.db import new_session
    from ngsirs_api.models import Employer, IngestBatch, Taxpayer

    with new_session(world.other) as db:
        other_count = db.execute(select(func.count()).select_from(Employer)).scalar_one()
        assert other_count > 0
        tenants = set(db.execute(select(Employer.tenant_id)).scalars())
        assert tenants == {world.other}
    with new_session(world.ngsirs) as db:
        assert set(db.execute(select(Taxpayer.tenant_id)).scalars()) == {world.ngsirs}
        assert set(db.execute(select(IngestBatch.tenant_id)).scalars()) == {world.ngsirs}
    with new_session(None) as db:  # no tenant bound: nothing visible
        assert db.execute(select(func.count()).select_from(Employer)).scalar_one() == 0


def test_database_rejects_writes_into_another_tenant(world: World) -> None:
    from sqlalchemy.exc import DBAPIError

    from ngsirs_api.db import new_session
    from ngsirs_api.models import Lga

    with new_session(world.ngsirs) as db, pytest.raises(DBAPIError):
        db.add(Lga(tenant_id=world.other, code="ZZZ", name="Injected", verified=False, pilot=False))
        db.flush()


def test_api_cannot_retrieve_other_tenant_records(client: TestClient, auth: dict, world: World) -> None:
    other = token_for(world.other, "ISOLATION-TEST-ORG", ["compliance_manager"], "other.manager")
    ngs_finding = findings(client, auth["manager"])[0]
    r = client.get(f"/api/v1/risks/{ngs_finding['finding_id']}", headers=other)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"  # no existence leak
    assert client.get("/api/v1/risks", headers=other).json()["total"] == 0
    ref = ngs_finding["subject"]["employer_ref"] or "NGS-DEMO-EMP-0001"
    other_view = client.get(f"/api/v1/taxpayers/{ref}", headers=other)
    # The isolation org loaded the same synthetic register, so the ref may exist there - but it must be its own row.
    if other_view.status_code == 200:
        assert other_view.json()["findings"] == []
    assert client.get("/api/v1/cases", headers=other).json() == []


def test_forged_tenant_claim_does_not_cross_tenants(client: TestClient, auth: dict, world: World) -> None:
    # A token claiming the NGSIRS tenant code but carrying the other tenant's id is scoped by the id.
    forged = token_for(world.other, "NGSIRS", ["compliance_manager"], "forged")
    assert client.get("/api/v1/risks", headers=forged).json()["total"] == 0


def test_scheduled_job_is_tenant_scoped(world: World) -> None:
    from ngsirs_api.db import tenant_session
    from ngsirs_api.models import EvaluationRun

    with tenant_session(world.other) as db:
        assert db.execute(select(func.count()).select_from(EvaluationRun)).scalar_one() == 0


# --- authentication -----------------------------------------------------------------------------


def test_requests_without_or_with_bad_tokens_are_rejected(client: TestClient, world: World) -> None:
    assert client.get("/api/v1/risks").status_code == 401
    assert client.get("/api/v1/risks", headers={"Authorization": "Bearer nope"}).status_code == 401
    expired = token_for(world.ngsirs, "NGSIRS", ["compliance_manager"], ttl=-120)
    r = client.get("/api/v1/risks", headers=expired)
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"
    norole = token_for(world.ngsirs, "NGSIRS", ["not_a_role"])
    assert client.get("/api/v1/risks", headers=norole).status_code == 403


def test_tampered_token_rejected(client: TestClient, auth: dict) -> None:
    header, payload, sig = auth["officer"]["Authorization"].split(" ")[1].split(".")
    tampered = f"{header}.{payload}.{sig[:-4]}AAAA"
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_mfa_enforced_when_required(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    from ngsirs_api.errors import ApiError
    from ngsirs_api.security import auth as auth_mod

    settings = auth_mod.get_settings()
    monkeypatch.setattr(settings, "require_mfa", True)
    claims = {
        "sub": "x",
        "tenant_id": str(world.ngsirs),
        "tenant": "NGSIRS",
        "roles": ["compliance_officer"],
        "amr": ["pwd"],
    }
    with pytest.raises(ApiError) as exc:
        auth_mod.principal_from_claims(claims)
    assert exc.value.code == "mfa_required"
    claims["amr"] = ["pwd", "mfa"]
    assert auth_mod.principal_from_claims(claims).mfa


def test_production_refuses_demo_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngsirs_api import config

    monkeypatch.setenv("NGSIRS_ENVIRONMENT", "production")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError):
            config.get_settings()
    finally:
        monkeypatch.setenv("NGSIRS_ENVIRONMENT", "test")
        config.get_settings.cache_clear()


# --- authorisation ------------------------------------------------------------------------------

ROLE_MATRIX = [
    # (user, method, path, expected)
    ("exec", "GET", "/api/v1/dashboard/summary", 200),
    ("exec", "GET", "/api/v1/risks", 403),
    ("exec", "GET", "/api/v1/taxpayers", 403),
    ("exec", "GET", "/api/v1/cases", 403),
    ("exec", "GET", "/api/v1/reports", 200),
    ("officer", "GET", "/api/v1/risks", 200),
    ("officer", "GET", "/api/v1/audit-events", 403),
    ("officer", "GET", "/api/v1/imports", 403),
    ("officer", "POST", "/api/v1/rules/evaluations", 403),
    ("steward", "GET", "/api/v1/imports", 200),
    ("steward", "GET", "/api/v1/data-quality/quarantine", 200),
    ("steward", "GET", "/api/v1/rules", 403),
    ("analyst", "GET", "/api/v1/rules", 200),
    ("analyst", "POST", "/api/v1/rules/evaluations", 403),
    ("audit", "GET", "/api/v1/audit-events", 200),
    ("admin", "GET", "/api/v1/audit-events", 200),
    ("admin", "GET", "/api/v1/risks", 403),
    ("legal", "GET", "/api/v1/legal/obligations", 200),
    ("legal", "POST", "/api/v1/imports", 403),
]


@pytest.mark.parametrize(("user", "method", "path", "expected"), ROLE_MATRIX)
def test_role_matrix(
    client: TestClient, auth: dict, user: str, method: str, path: str, expected: int
) -> None:
    body = {"as_of": "2026-10-01T00:00:00+01:00", "period_from": "2025-09", "period_to": "2026-08"}
    r = client.request(method, path, headers=auth[user], json=body if method == "POST" else None)
    assert r.status_code == expected if expected != 200 else r.status_code in (200, 201), (user, path, r.text)


def test_lga_scoped_officer_sees_only_assigned_lgas(client: TestClient, auth: dict) -> None:
    scoped = findings(client, auth["field"], open_only=False)
    assert scoped and {f["lga"] for f in scoped} <= {"CHA", "BOS"}
    everything = findings(client, auth["officer"], open_only=False)
    assert len(everything) > len(scoped)
    outside = next(f for f in everything if f["lga"] not in ("CHA", "BOS"))
    assert client.get(f"/api/v1/risks/{outside['finding_id']}", headers=auth["field"]).status_code == 404


def test_purpose_required_for_identifier_reveal(client: TestClient, auth: dict, world: World) -> None:
    ref = world.scenarios["clean"][0]
    url = f"/api/v1/taxpayers/{ref}/identifiers/reveal"
    assert client.post(url, headers=auth["steward"]).status_code == 403
    assert (
        client.post(url, headers={**auth["steward"], "X-Purpose": "management_reporting"}).status_code == 403
    )
    r = client.post(url, headers={**auth["steward"], "X-Purpose": "data_quality"})
    assert r.status_code == 200 and r.json()["identifiers"][0]["value"].startswith("NGS-DEMO-TIN-")
    assert client.post(url, headers={**auth["officer"], "X-Purpose": "case_review"}).status_code == 403
    events = client.get(
        "/api/v1/audit-events", headers=auth["audit"], params={"event_type": "taxpayer.identifier_revealed"}
    ).json()["items"]
    assert events and events[0]["purpose"] == "data_quality"


def test_identifiers_are_encrypted_and_tokenised_at_rest(world: World) -> None:
    from ngsirs_api.db import new_session
    from ngsirs_api.models import TaxpayerIdentifier

    with new_session(world.ngsirs) as db:
        ident = db.execute(select(TaxpayerIdentifier)).scalars().first()
        assert ident is not None
        assert b"NGS-DEMO-TIN" not in ident.encrypted_value
        assert len(ident.token) == 64 and ident.masked.startswith("*")


# --- tamper evidence ----------------------------------------------------------------------------


def test_audit_events_are_append_only_for_the_application(world: World) -> None:
    from sqlalchemy.exc import DBAPIError

    from ngsirs_api.db import new_session

    with new_session(world.ngsirs) as db, pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_event SET actor_id = 'someone-else'"))
    with new_session(world.ngsirs) as db, pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_event"))


def test_approved_rule_version_is_immutable(world: World) -> None:
    from sqlalchemy.exc import DBAPIError

    from ngsirs_api.db import new_session

    with new_session(world.ngsirs) as db, pytest.raises(DBAPIError) as exc:
        db.execute(text("UPDATE rule_version SET expression_json = '{}'::jsonb WHERE status = 'active'"))
    assert "immutable" in str(exc.value)


def test_audit_chain_detects_tampering(client: TestClient, auth: dict, world: World) -> None:
    assert client.get("/api/v1/audit-events/verify", headers=auth["audit"]).json()["valid"] is True
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
    with psycopg.connect(url, autocommit=True) as conn:
        # A superuser bypassing the application's controls edits history...
        conn.execute("ALTER TABLE audit_event DISABLE TRIGGER audit_event_append_only")
        seq, original = conn.execute(
            "SELECT seq, actor_id FROM audit_event WHERE tenant_id = %s ORDER BY seq LIMIT 1", (world.ngsirs,)
        ).fetchone()
        conn.execute(
            "UPDATE audit_event SET actor_id = 'intruder' WHERE tenant_id = %s AND seq = %s",
            (world.ngsirs, seq),
        )
        try:
            result = client.get("/api/v1/audit-events/verify", headers=auth["audit"]).json()
            assert result["valid"] is False and result["broken_at_seq"] == seq
        finally:
            conn.execute(
                "UPDATE audit_event SET actor_id = %s WHERE tenant_id = %s AND seq = %s",
                (original, world.ngsirs, seq),
            )
            conn.execute("ALTER TABLE audit_event ENABLE TRIGGER audit_event_append_only")
    assert client.get("/api/v1/audit-events/verify", headers=auth["audit"]).json()["valid"] is True


def test_error_contract_has_trace_id(client: TestClient, auth: dict) -> None:
    r = client.get("/api/v1/risks/00000000-0000-0000-0000-000000000000", headers=auth["officer"])
    body = r.json()["error"]
    assert r.status_code == 404 and body["trace_id"] and r.headers["X-Trace-Id"] == body["trace_id"]
    r = client.get("/api/v1/risks", headers=auth["officer"], params={"page": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
