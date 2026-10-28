"""Golden fixture and PRD section 15 acceptance tests (plus Tech Spec section 17 scenarios)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FIXTURES
from tests.integration.conftest import World, findings

pytestmark = pytest.mark.integration


def test_golden_fixture_matches_independently_declared_expectations(world: World) -> None:
    g = world.golden
    assert g["missing"] == [] and g["unexpected"] == [], g
    assert g["expected"] == g["actual"] == 129


def test_fixture_contract_size(world: World) -> None:
    employers = (FIXTURES / "employers.csv").read_text().strip().splitlines()[1:]
    assert len(employers) >= 120
    assert any(",CHA," in e or ",BOS," in e for e in employers)  # Minna pilot LGAs present


def test_reprocessing_same_batch_and_rules_is_idempotent(world: World) -> None:
    from ngsirs_api import cli

    before = cli.actual_findings(world.ngsirs)
    loads = cli.load_fixtures(world.ngsirs)
    assert all(not r["created"] for r in loads)  # same files -> existing batches returned
    run = cli.evaluate(world.ngsirs, world.as_of, world.manifest["period_from"], world.manifest["period_to"])
    assert run["reused"] is True
    assert cli.actual_findings(world.ngsirs) == before


def test_approved_extension_prevents_fil001(client: TestClient, auth: dict, world: World) -> None:
    for ref in world.scenarios["extension_granted"]:
        rules = {f["rule"]["id"] for f in findings(client, auth["officer"], employer=ref, open_only=False)}
        assert not rules & {"FIL-001", "FIL-002"}


def test_return_accepted_before_due_with_late_ingestion_does_not_fire(
    client: TestClient, auth: dict, world: World
) -> None:
    for ref in world.scenarios["late_ingest"]:
        assert findings(client, auth["officer"], employer=ref, open_only=False) == []


def test_suspense_payment_flags_treasury_reconciliation_not_non_payment(
    client: TestClient, auth: dict, world: World
) -> None:
    receipts = {f["subject"]["id"]: f for f in findings(client, auth["steward"], rule="PAY-005")}
    for ref in world.scenarios["suspense_receipt"]:
        n = ref.rsplit("-", 1)[1]
        receipt = receipts[f"NGS-DEMO-PAY-{n}-2026-07"]
        assert receipt["signal_class"] == "data_quality" and receipt["treatment"] == "treasury_reconciliation"
        assert receipt["priority_score"] is None
        assert findings(client, auth["officer"], employer=ref, rule="PAY-001") == []


def test_unverified_match_cannot_generate_taxpayer_notice(
    client: TestClient, auth: dict, world: World
) -> None:
    ref = world.scenarios["unverified_identity"][0]
    held = findings(client, auth["officer"], employer=ref, rule="FIL-001")[0]
    assert held["flags"]["data_hold"] and "identity_unverified" in held["holds"]
    r = client.post(
        "/api/v1/cases",
        headers=auth["officer"],
        json={
            "finding_id": held["finding_id"],
            "rationale": "Attempt reminder",
            "treatment": "review_then_approved_reminder",
        },
    )
    assert r.status_code == 409
    r = client.post(
        "/api/v1/cases",
        headers=auth["steward"],
        json={
            "finding_id": held["finding_id"],
            "rationale": "Verify identity first",
            "treatment": "identity_review",
        },
    )
    assert r.status_code == 201, r.text
    case = r.json()
    r = client.post(
        f"/api/v1/cases/{case['id']}/approve", headers=auth["manager"], json={"note": "Internal only"}
    )
    assert r.status_code == 403  # identity_review must be approved by a data steward
    r = client.post(f"/api/v1/cases/{case['id']}/approve", headers=auth["steward"], json={"note": "self"})
    assert r.status_code == 403 and "creator" in r.json()["error"]["message"]
    r = client.post(
        f"/api/v1/cases/{case['id']}/approve", headers=auth["steward2"], json={"note": "Verify match"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["outward_permitted"] is False
    assert {"treatment_is_internal", "data_hold", "identity_unverified"} <= set(r.json()["outward_blockers"])


def test_pre_2026_period_uses_prior_legal_version(client: TestClient, auth: dict, world: World) -> None:
    for ref in world.scenarios["legal_transition"]:
        late = findings(client, auth["officer"], employer=ref, rule="FIL-002")
        assert [f["tax_period"] for f in late] == ["2025-12"]
        detail = client.get(f"/api/v1/risks/{late[0]['finding_id']}", headers=auth["officer"]).json()
        assert detail["legal_version"] == "PAYE_EMPLOYER_MONTHLY_RETURN@2020.1-SYN"
    old = client.get(
        "/api/v1/legal/resolve",
        headers=auth["analyst"],
        params={"code": "PAYE_EMPLOYER_MONTHLY_RETURN", "period": "2025-12"},
    ).json()
    new = client.get(
        "/api/v1/legal/resolve",
        headers=auth["analyst"],
        params={"code": "PAYE_EMPLOYER_MONTHLY_RETURN", "period": "2026-01"},
    ).json()
    assert old["approved_version"]["version"] == "2020.1-SYN" and old["due_at"].startswith("2026-01-10")
    assert new["approved_version"]["version"] == "2026.1-SYN" and new["due_at"].startswith("2026-02-15")


def test_no_employee_count_means_reporting_risk_unknown(client: TestClient, auth: dict, world: World) -> None:
    for ref in world.scenarios["clean"][:30]:
        t = client.get(f"/api/v1/taxpayers/{ref}", headers=auth["officer"]).json()
        if t["reporting_risk"]["status"] == "unknown":
            assert "unknown, not zero" in t["reporting_risk"]["note"]
            return
    pytest.fail("fixture should contain an employer with no employee-count evidence")


def test_no_obligation_is_distinguished(client: TestClient, auth: dict, world: World) -> None:
    for ref in world.scenarios["no_obligation"]:
        t = client.get(f"/api/v1/taxpayers/{ref}", headers=auth["officer"]).json()
        assert t["obligation_summary"] == "no_obligation_record"
        assert {p["obligation_status"] for p in t["periods"]} == {"none"}
        assert t["findings"] == []


def test_appeal_blocks_enforcement_workflow(client: TestClient, auth: dict, world: World) -> None:
    held = [f for f in findings(client, auth["manager"], rule="PAY-006") if f["flags"]["legal_hold"]]
    assert len(held) == len(world.scenarios["assessment_appealed"])
    f = held[0]
    assert f["allowed_next_action"] == "internal_review_only" and f["priority_score"] is not None
    case = client.post(
        "/api/v1/cases",
        headers=auth["officer"],
        json={
            "finding_id": f["finding_id"],
            "rationale": "Debt reconciliation",
            "treatment": "debt_reconciliation",
        },
    ).json()
    approved = client.post(
        f"/api/v1/cases/{case['id']}/approve", headers=auth["manager"], json={"note": "Reconcile only"}
    ).json()
    assert approved["outward_permitted"] is False and "legal_hold" in approved["outward_blockers"]
    r = client.post(
        f"/api/v1/cases/{case['id']}/actions",
        headers=auth["officer"],
        json={
            "action_type": "contact_taxpayer",
            "detail": "Demand",
            "template_code": "PAYE_PAYMENT_ENGAGEMENT_V1",
        },
    )
    assert r.status_code == 409


def test_conflicting_sources_route_to_reconciliation(client: TestClient, auth: dict, world: World) -> None:
    dat3 = {(f["subject"]["id"], f["tax_period"]) for f in findings(client, auth["steward"], rule="DAT-003")}
    for ref in world.scenarios["filing_source_conflict"]:
        assert (ref, "2026-02") in dat3
    for ref in world.scenarios["payment_source_conflict"]:
        assert (ref, "2026-05") in dat3
        assert findings(client, auth["officer"], employer=ref, rule="PAY-004") == []


def test_invalid_identifiers_and_periods_go_to_data_quality_queue(client: TestClient, auth: dict) -> None:
    q = client.get("/api/v1/data-quality/quarantine", headers=auth["steward"]).json()
    reasons = {r for row in q for r in row["reasons"]}
    assert {"invalid_identifier", "invalid_period"} <= reasons
    dat2 = findings(client, auth["steward"], rule="DAT-002")
    assert dat2 and all(f["signal_class"] == "data_quality" and f["priority_score"] is None for f in dat2)


def test_explanation_payload_shape(client: TestClient, auth: dict) -> None:
    f = findings(client, auth["officer"], rule="FIL-001", hold="none")[0]
    e = client.get(f"/api/v1/risks/{f['finding_id']}/explanation", headers=auth["officer"]).json()
    assert e["rule"]["id"] == "FIL-001" and e["indicators"]["consequence"] is None
    assert e["priority_score"] is None and e["priority_note"] == "exposure_unknown"
    assert e["gates"]["identity_verified"] is True and e["allowed_next_action"] == "internal_review"
    assert e["evidence_refs"] and e["label"] == "Risk indicator, not finding of evasion"


def test_every_finding_is_explainable_and_reproducible(client: TestClient, auth: dict) -> None:
    items = findings(client, auth["manager"])
    assert items
    for f in items[:40]:
        d = client.get(f"/api/v1/risks/{f['finding_id']}", headers=auth["manager"]).json()
        assert d["explanation"] and d["evidence_refs"] and d["snapshot"]["facts_hash"]
        assert d["rule"]["version"] and d["tax_period"] or d["subject"]["type"] != "employer"
        if d["signal_class"] != "data_quality" or d["flags"]["data_hold"]:
            assert d["legal_version"] or d["subject"]["type"] != "employer"
        rep = client.post(f"/api/v1/risks/{f['finding_id']}/reproduce", headers=auth["manager"]).json()
        assert rep["reproduced"] is True, rep


def test_dashboard_metrics_carry_denominators(client: TestClient, auth: dict) -> None:
    d = client.get("/api/v1/dashboard/summary", headers=auth["exec"]).json()
    by_key = {m["key"]: m for m in d["metrics"]}
    filing = by_key["paye_on_time_filing"]
    assert filing["denominator"] and filing["numerator"] is not None and filing["window"]
    assert filing["completeness"] is not None
    assert "Confirmed served assessments only" in by_key["confirmed_arrears"]["caveats"][0]
    assert d["trend"] and all("denominator" in t["filing"] for t in d["trend"])
    assert "SYNTHETIC" in d["method_note"]
