"""Shared pytest fixtures for unit and acceptance suites (synthetic data only)."""

import os

os.environ.setdefault("TAXCRIS_AS_OF", "2026-10-21")
os.environ.setdefault("TAXCRIS_INLINE_JOBS", "true")

import uuid  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from . import db as dbmod  # noqa: E402
from .db import Base  # noqa: E402
from .domain.ingestion import records_checksum  # noqa: E402
from .main import create_app  # noqa: E402
from .models import Tenant, User  # noqa: E402
from .routers import auth as auth_router  # noqa: E402
from .security import create_access_token  # noqa: E402
from . import seed  # noqa: E402


@dataclass
class Env:
    client: TestClient
    tenants: dict[str, Tenant]
    users: dict[str, dict[str, User]]
    _tokens: dict[str, str] = field(default_factory=dict)

    def h(self, handle: str, tenant: str = "NI") -> dict[str, str]:
        """Auth header for a seeded user, e.g. env.h('analyst')."""
        key = f"{tenant}:{handle}"
        if key not in self._tokens:
            u = self.users[tenant][handle]
            self._tokens[key] = create_access_token(u.id, u.tenant_id, u.role)
        return {"Authorization": f"Bearer {self._tokens[key]}"}

    def user_id(self, handle: str, tenant: str = "NI") -> str:
        return str(self.users[tenant][handle].id)

    def import_records(self, dataset: str, records: list[dict], source: str = "TEST-SRC", tenant: str = "NI",
                       handle: str = "steward", extracted_at: str = "2026-10-18", key: str | None = None):
        body = {"dataset": dataset, "source_system": source, "idempotency_key": key or f"k-{uuid.uuid4()}",
                "checksum": records_checksum(records), "extracted_at": extracted_at, "records": records}
        return self.client.post("/v1/imports", json=body, headers=self.h(handle, tenant))


@pytest.fixture
def env():
    # Set TAXCRIS_TEST_DATABASE_URL to run the suites against PostgreSQL (as CI does).
    engine = dbmod.configure(os.environ.get("TAXCRIS_TEST_DATABASE_URL", "sqlite:///:memory:"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    auth_router._ATTEMPTS.clear()
    with dbmod.session_factory()() as db:
        ni, ni_users = seed.create_tenant(db, "NI", "Niger State Internal Revenue Service", "niger.test")
        seed.seed_rules(db, ni, ni_users)
        seed.seed_model(db, ni, ni_users)
        kw, kw_users = seed.create_tenant(db, "KW", "Kwara State Internal Revenue Service", "kwara.test")
        seed.seed_rules(db, kw, kw_users)
        seed.seed_model(db, kw, kw_users)
        db.commit()
    yield Env(TestClient(create_app()), {"NI": ni, "KW": kw}, {"NI": ni_users, "KW": kw_users})
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------------------------
# A compact, fully fictional dataset with one taxpayer per behaviour.
# ---------------------------------------------------------------------------------------------

PERIODS = [f"2025-{m:02d}" for m in range(10, 13)] + [f"2026-{m:02d}" for m in range(1, 10)]


def _deadline(period: str) -> date:
    y, m = int(period[:4]), int(period[5:])
    first_next = date(y + (m == 12), m % 12 + 1, 1)
    return first_next - timedelta(days=1) + timedelta(days=10)


def small_dataset() -> dict[str, list[dict]]:
    taxpayers = [
        {"source_record_id": "B1", "taxpayer_type": "business", "name": "Kpada Fresh Farms Ltd", "tin": "SYN-T0000001",
         "tax_residence": "NI", "lga": "Bida", "sector": "Agriculture", "is_employer": True, "registered_on": "2019-01-01"},
        {"source_record_id": "B2", "taxpayer_type": "business", "name": "Gurara Building Works Ltd", "tin": "SYN-T0000002",
         "tax_residence": "NI", "lga": "Suleja", "sector": "Construction", "is_employer": True, "registered_on": "2019-01-01"},
        {"source_record_id": "B3", "taxpayer_type": "business", "name": "Zuma Logistics Ltd", "tin": "SYN-T0000003",
         "tax_residence": "NI", "lga": "Chanchaga", "sector": "Transport", "is_employer": True, "registered_on": "2019-01-01"},
        {"source_record_id": "B4", "taxpayer_type": "business", "name": "Tagwai Hotels Ltd", "cac_rc": "SYN-RC4",
         "registration_status": "unregistered", "tax_residence": "NI", "lga": "Bosso", "sector": "Hospitality",
         "is_employer": True},
        {"source_record_id": "B5", "taxpayer_type": "business", "name": "Edu Rice Processing Ltd", "tin": "SYN-T0000005",
         "tax_residence": "NI", "lga": "Lapai", "sector": "Agriculture", "is_employer": True, "operating_status": "closed",
         "closed_on": "2025-09-30", "registered_on": "2015-01-01"},
        {"source_record_id": "I1", "taxpayer_type": "individual", "name": "Aisha Ndayako", "tin": "SYN-T0000006",
         "nin": "SYN0000000006", "tax_residence": "NI", "lga": "Bida", "sector": "Retail"},
    ]
    returns, payments = [], []
    for period in PERIODS:
        d = _deadline(period)
        for tin, profile in (("SYN-T0000001", "compliant"), ("SYN-T0000002", "non_filer"), ("SYN-T0000003", "underpayer")):
            if profile == "non_filer" and period >= "2026-03":
                continue
            filed = d - timedelta(days=2)
            returns.append({"source_record_id": f"R-{tin[-2:]}-{period}", "tin": tin, "tax_type": "PAYE", "period": period,
                            "filing_date": filed.isoformat(), "reported_income": "1000000.00", "reported_amount": "70000.00"})
            amount = "70000.00" if not (profile == "underpayer" and period >= "2026-01") else "30000.00"
            payments.append({"source_record_id": f"P-{tin[-2:]}-{period}", "tin": tin, "tax_type": "PAYE", "period": period,
                             "amount": amount, "payment_date": filed.isoformat()})
    employments = [{"source_record_id": "E1", "employer_tin": "SYN-T0000001", "employee_tin": "SYN-T0000006",
                    "start_date": "2020-01-01", "monthly_gross": "250000.00"}]
    return {"taxpayers": taxpayers, "employments": employments, "returns": returns, "payments": payments}


def load_small(env: Env, tenant: str = "NI") -> dict[str, dict]:
    out = {}
    for dataset, records in small_dataset().items():
        r = env.import_records(dataset, records, tenant=tenant)
        assert r.status_code == 202, r.text
        out[dataset] = r.json()
    return out


def taxpayer_id(env: Env, name: str, handle: str = "analyst", tenant: str = "NI") -> str:
    r = env.client.get("/v1/taxpayers", params={"q": name}, headers=env.h(handle, tenant))
    assert r.status_code == 200, r.text
    return r.json()["items"][0]["id"]
