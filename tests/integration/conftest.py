from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import ADMIN_URL, FIXTURES, REPO, TEST_DB


def _admin(sql: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql)


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    _admin((REPO / "infra" / "db" / "init.sql").read_text())
    _admin(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    _admin(f"CREATE DATABASE {TEST_DB} OWNER taxrisk_owner")
    from taxrisk_api.cli import migrate

    migrate()
    yield


class World:
    """Handles to the seeded authority tenant and the isolation-test organisation."""

    def __init__(
        self, authority: uuid.UUID, other: uuid.UUID, manifest: dict[str, Any], golden: dict[str, Any]
    ):
        self.authority = authority
        self.other = other
        self.manifest = manifest
        self.golden = golden
        self.as_of = datetime.fromisoformat(manifest["as_of"])
        self.scenarios = {}
        for line in (FIXTURES / "scenarios.csv").read_text().splitlines()[1:]:
            ref, scenario, _ = line.split(",")
            self.scenarios.setdefault(scenario, []).append(ref)


@pytest.fixture(scope="session")
def world(database: None) -> World:
    from taxrisk_api import cli
    from taxrisk_api.db import tenant_session
    from taxrisk_api.jurisdiction import load_pack
    from taxrisk_api.models import Tenant
    from taxrisk_api.seed import bootstrap_tenant, seed_all, seed_reference

    authority = seed_all()
    loads = cli.load_fixtures(authority)
    assert all(r["status"] == "committed" for r in loads), loads
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    cli.evaluate(
        authority, datetime.fromisoformat(manifest["as_of"]), manifest["period_from"], manifest["period_to"]
    )
    golden = cli.compare_golden(authority)

    other = bootstrap_tenant(
        "ISOLATION-TEST-ORG", "Isolation test organisation (tests only)", is_test_only=True
    )
    with tenant_session(other) as db:
        seed_reference(db, other, load_pack("demo"))
        t = db.execute(select(Tenant)).scalar_one()
        assert t.is_test_only
    cli.load_fixtures(other)
    return World(authority, other, manifest, golden)


@pytest.fixture(scope="session")
def client(world: World) -> Iterator[TestClient]:
    from taxrisk_api.main import app

    with TestClient(app) as c:
        yield c


USERS = {
    "officer": "compliance.officer",
    "manager": "compliance.manager",
    "manager2": "compliance.manager2",
    "analyst": "risk.analyst",
    "analyst2": "risk.analyst2",
    "legal": "legal.approver",
    "steward": "data.steward",
    "steward2": "data.steward2",
    "audit": "audit.officer",
    "exec": "executive.chairman",
    "admin": "platform.admin",
    "field": "field.officer.central",
    "services": "taxpayer.services",
}


@pytest.fixture(scope="session")
def auth(client: TestClient) -> dict[str, dict[str, str]]:
    out = {}
    for key, username in USERS.items():
        r = client.post("/api/v1/auth/dev-token", json={"username": username})
        assert r.status_code == 200, r.text
        out[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


def token_for(
    tenant_id: uuid.UUID,
    tenant_code: str,
    roles: list[str],
    username: str = "test.user",
    purposes: list[str] | None = None,
    ttl: int | None = None,
) -> dict[str, str]:
    from taxrisk_api.security.auth import issue_dev_token

    tok = issue_dev_token(username, username, tenant_id, tenant_code, roles, purposes or [], [], ttl=ttl)
    return {"Authorization": f"Bearer {tok}"}


def findings(client: TestClient, headers: dict[str, str], **params: Any) -> list[dict[str, Any]]:
    params.setdefault("page_size", 500)
    r = client.get("/api/v1/risks", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]
