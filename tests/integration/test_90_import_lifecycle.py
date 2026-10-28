"""Import pipeline via the API: preview, commit, idempotent re-upload, rollback, coverage and external sources.

Runs last: it changes canonical data and re-evaluates.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES
from tests.integration.conftest import World, findings

pytestmark = pytest.mark.integration
AS_OF = "2026-10-01T00:00:00+01:00"
EVAL = {"as_of": AS_OF, "period_from": "2025-09", "period_to": "2026-08"}


def _upload(client: TestClient, headers: dict, name: str, content: bytes, **form: str) -> dict:
    r = client.post(
        "/api/v1/imports",
        headers=headers,
        files={"file": (name, content, "text/csv")},
        data={
            "source": "ngsirs_etax_portal",
            "feed_type": "ngsirs_paye_return",
            "extracted_at": "2026-09-30T14:00:00+01:00",
            **form,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_external_source_without_legal_basis_is_refused(client: TestClient, auth: dict) -> None:
    r = client.post(
        "/api/v1/imports",
        headers=auth["steward"],
        files={"file": ("e.csv", b"x\n1\n", "text/csv")},
        data={
            "source": "external_business_licensing",
            "feed_type": "ngsirs_employer",
            "extracted_at": "2026-09-30T14:00:00+01:00",
        },
    )
    assert r.status_code == 403


def test_invalid_file_is_rejected_with_reasons(client: TestClient, auth: dict) -> None:
    b = _upload(client, auth["steward"], "bad.csv", b"filing_reference,period\nX,2026-01\n")
    assert b["qa_status"] == "rejected" and any("employer_id" in e for e in b["quality"]["header_errors"])
    assert client.post(f"/api/v1/imports/{b['id']}/commit", headers=auth["steward"]).status_code == 409


def test_rollback_and_reimport_of_late_batch(client: TestClient, auth: dict, world: World) -> None:
    batches = client.get(
        "/api/v1/imports", headers=auth["steward"], params={"feed_type": "ngsirs_paye_return"}
    ).json()
    late = next(b for b in batches if b["file_name"] == "paye_returns_late.csv")
    refs = world.scenarios["late_ingest"]
    assert all(findings(client, auth["officer"], employer=r, rule="FIL-001") == [] for r in refs)

    assert (
        client.post(
            f"/api/v1/imports/{late['id']}/rollback", headers=auth["officer"], json={"reason": "x" * 5}
        ).status_code
        == 403
    )
    rb = client.post(
        f"/api/v1/imports/{late['id']}/rollback",
        headers=auth["steward"],
        json={"reason": "Extract sent in error"},
    ).json()
    assert rb["qa_status"] == "rolled_back"
    assert client.post("/api/v1/rules/evaluations", headers=auth["manager"], json=EVAL).status_code == 201
    for r in refs:  # the accepted return is gone, coverage says complete -> verified missing return
        assert [f["tax_period"] for f in findings(client, auth["officer"], employer=r, rule="FIL-001")] == [
            "2026-08"
        ]

    content = (FIXTURES / "paye_returns_late.csv").read_bytes()
    again = _upload(client, auth["steward"], "paye_returns_late.csv", content)
    assert again["created"] is True and again["qa_status"] == "validated"
    dup = _upload(client, auth["steward"], "paye_returns_late.csv", content)
    assert dup["created"] is False and dup["id"] == again["id"]
    preview = client.get(f"/api/v1/imports/{again['id']}/rows", headers=auth["steward"]).json()
    assert preview["total"] == 2
    assert (
        client.post(f"/api/v1/imports/{again['id']}/commit", headers=auth["steward"]).json()["qa_status"]
        == "committed"
    )
    assert client.post("/api/v1/rules/evaluations", headers=auth["manager"], json=EVAL).status_code == 201
    for r in refs:  # condition no longer met -> withdrawn in the taxpayer's favour
        assert findings(client, auth["officer"], employer=r, rule="FIL-001") == []
        gone = findings(client, auth["officer"], employer=r, rule="FIL-001", open_only=False)
        assert {f["status"] for f in gone} == {"withdrawn"}


def test_incomplete_coverage_suppresses_missing_filing(client: TestClient, auth: dict, world: World) -> None:
    """A period not covered by any filing extract is unknown, never 'missing' (Tech Spec 17, row 1)."""
    run = client.post(
        "/api/v1/rules/evaluations", headers=auth["manager"], json={**EVAL, "period_to": "2026-09"}
    ).json()
    assert run["counts"]["suppression_reasons"].get("filing_coverage_incomplete", 0) > 0
    assert findings(client, auth["officer"], rule="FIL-001", period="2026-09") == []


def test_stale_sources_put_findings_on_data_hold(client: TestClient, auth: dict, world: World) -> None:
    """Evaluating long after the last extract: every new taxpayer signal becomes a data hold."""
    run = client.post(
        "/api/v1/rules/evaluations",
        headers=auth["manager"],
        json={**EVAL, "as_of": "2026-10-20T00:00:00+01:00"},
    ).json()
    assert run["counts"]["hold_reasons"].get("stale_source", 0) > 0
    held = [f for f in findings(client, auth["officer"], rule="FIL-001") if "stale_source" in f["holds"]]
    assert held and all(f["priority_score"] is None and f["flags"]["data_hold"] for f in held)
