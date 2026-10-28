"""Governance workflows: reviews, overrides, cases, evidence, rule and legal maker-checker, programmes."""

from __future__ import annotations

import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import World, findings

pytestmark = pytest.mark.integration
AS_OF = "2026-10-01T00:00:00+01:00"


def _open_finding(client: TestClient, auth: dict, **params: object) -> dict:
    for f in findings(client, auth["manager"], hold="none", **params):
        if f["case"] is None and f["status"] == "review_required":
            return f
    raise AssertionError(f"no open finding without case for {params}")


def test_manager_override_records_actor_time_reason_and_previous(client: TestClient, auth: dict) -> None:
    f = _open_finding(client, auth, rule="PAY-001")
    before = client.get(f"/api/v1/risks/{f['finding_id']}", headers=auth["manager"]).json()
    r = client.post(
        f"/api/v1/risks/{f['finding_id']}/override",
        headers=auth["manager"],
        json={
            "likelihood": 5,
            "reason": "Known repeat pattern from field visit",
            "expected_version": before["version"],
        },
    )
    assert r.status_code == 200, r.text
    o = r.json()["override"]
    assert o["actor"] == "compliance.manager" and o["at"] and o["reason"].startswith("Known")
    assert o["previous"]["likelihood"] == before["indicators"]["likelihood"]
    assert r.json()["engine_outcome"]["likelihood"] == before["indicators"]["likelihood"]  # engine value kept
    events = client.get(
        "/api/v1/audit-events",
        headers=auth["audit"],
        params={"subject": f"finding:{f['finding_ref']}", "event_type": "finding.override"},
    ).json()
    assert events["items"][0]["actor"] == "compliance.manager"
    assert (
        client.post(
            f"/api/v1/risks/{f['finding_id']}/override",
            headers=auth["officer"],
            json={"likelihood": 1, "reason": "nope"},
        ).status_code
        == 403
    )


def test_optimistic_concurrency_conflict(client: TestClient, auth: dict) -> None:
    f = _open_finding(client, auth, rule="FIL-002")
    stale = f["version"]
    ok = client.post(
        f"/api/v1/risks/{f['finding_id']}/review",
        headers=auth["officer"],
        json={
            "decision": "mark_disputed",
            "reason": "Taxpayer says filed on time",
            "expected_version": stale,
        },
    )
    assert ok.status_code == 200
    r = client.post(
        f"/api/v1/risks/{f['finding_id']}/review",
        headers=auth["officer"],
        json={"decision": "clear_disputed", "reason": "retry", "expected_version": stale},
    )
    assert r.status_code == 409 and r.json()["error"]["details"]["current_version"] == stale + 1
    assert ok.json()["flags"]["disputed"] and ok.json()["allowed_next_action"] == "internal_review_only"


def test_review_requires_reason_and_valid_decision(client: TestClient, auth: dict) -> None:
    f = _open_finding(client, auth, rule="FIL-002")
    assert (
        client.post(
            f"/api/v1/risks/{f['finding_id']}/review",
            headers=auth["officer"],
            json={"decision": "confirm", "reason": ""},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/risks/{f['finding_id']}/review",
            headers=auth["officer"],
            json={"decision": "levy_penalty", "reason": "x" * 5},
        ).status_code
        == 422
    )


def test_idempotency_key_replays_case_creation(client: TestClient, auth: dict) -> None:
    f = _open_finding(client, auth, rule="PAY-002")
    key = str(uuid.uuid4())
    body = {"finding_id": f["finding_id"], "rationale": "Late remittance pattern"}
    a = client.post("/api/v1/cases", headers={**auth["officer"], "Idempotency-Key": key}, json=body)
    b = client.post("/api/v1/cases", headers={**auth["officer"], "Idempotency-Key": key}, json=body)
    assert a.status_code == 201 and b.status_code == 201 and a.json()["id"] == b.json()["id"]
    c = client.post(
        "/api/v1/cases",
        headers={**auth["officer"], "Idempotency-Key": key},
        json={**body, "rationale": "different"},
    )
    assert c.status_code == 409
    assert (
        client.post("/api/v1/cases", headers=auth["officer"], json=body).status_code == 409
    )  # one active case


def test_full_case_lifecycle_with_signed_evidence(client: TestClient, auth: dict) -> None:
    f = _open_finding(client, auth, rule="FIL-001")
    case = client.post(
        "/api/v1/cases",
        headers=auth["officer"],
        json={
            "finding_id": f["finding_id"],
            "rationale": "Verified missing return",
            "assigned_to": "compliance.officer",
        },
    ).json()
    assert case["stage"] == "pending_approval"
    r = client.post(
        f"/api/v1/cases/{case['id']}/actions",
        headers=auth["officer"],
        json={
            "action_type": "contact_taxpayer",
            "detail": "early",
            "template_code": "PAYE_RETURN_REMINDER_V1",
        },
    )
    assert r.status_code == 409  # not approved yet
    approved = client.post(
        f"/api/v1/cases/{case['id']}/approve",
        headers=auth["manager"],
        json={"note": "Reminder approved", "expected_version": case["version"]},
    ).json()
    assert approved["stage"] == "approved" and approved["outward_permitted"] is True
    assert approved["finding"]["status"] == "approved_for_treatment"
    bad = client.post(
        f"/api/v1/cases/{case['id']}/actions",
        headers=auth["officer"],
        json={"action_type": "contact_taxpayer", "detail": "x", "template_code": "FREE_TEXT"},
    )
    assert bad.status_code == 422
    sent = client.post(
        f"/api/v1/cases/{case['id']}/actions",
        headers=auth["officer"],
        json={
            "action_type": "contact_taxpayer",
            "detail": "Reminder issued",
            "template_code": "PAYE_RETURN_REMINDER_V1",
        },
    ).json()
    assert sent["stage"] == "awaiting_response"
    assert sent["actions"][-1]["delivery_status"] == "not_sent_demo_environment"
    assert sent["finding"]["status"] == "treated"
    client.post(
        f"/api/v1/cases/{case['id']}/actions",
        headers=auth["officer"],
        json={"action_type": "taxpayer_response", "detail": "Employer will file this week"},
    )
    assert (
        client.post(f"/api/v1/cases/{case['id']}/evidence-packet", headers=auth["officer"]).status_code == 403
    )
    pk = client.post(
        f"/api/v1/cases/{case['id']}/evidence-packet", headers={**auth["audit"], "X-Purpose": "desk_review"}
    ).json()
    assert pk["algorithm"] == "Ed25519" and pk["packet"]["finding"]["rule"].startswith("FIL-001@")
    assert pk["packet"]["notice"].startswith("Risk indicator, not finding of evasion")
    ok = client.post(
        "/api/v1/evidence-packets/verify",
        headers=auth["manager"],
        json={"packet": pk["packet"], "signature": pk["signature"]},
    ).json()
    assert ok["valid"] and ok["sha256"] == pk["sha256"]
    tampered = copy.deepcopy(pk["packet"])
    tampered["finding"]["likelihood"] = 5
    assert (
        client.post(
            "/api/v1/evidence-packets/verify",
            headers=auth["manager"],
            json={"packet": tampered, "signature": pk["signature"]},
        ).json()["valid"]
        is False
    )
    closed = client.post(
        f"/api/v1/cases/{case['id']}/close",
        headers=auth["officer"],
        json={"finding_outcome": "closed_confirmed", "note": "Return filed after reminder"},
    ).json()
    assert closed["stage"] == "closed" and closed["finding"]["status"] == "closed_confirmed"
    trail = client.get(f"/api/v1/risks/{f['finding_id']}", headers=auth["manager"]).json()["events"]
    states = [e["to"] for e in trail if e["type"] == "state_change"]
    assert states == ["validated", "review_required", "approved_for_treatment", "treated", "closed_confirmed"]


def test_batch_approval_skips_ineligible_cases(client: TestClient, auth: dict) -> None:
    a = _open_finding(client, auth, rule="PAY-002")
    good = client.post(
        "/api/v1/cases",
        headers=auth["officer"],
        json={"finding_id": a["finding_id"], "rationale": "Batch engagement"},
    ).json()
    b = _open_finding(client, auth, rule="FIL-002")
    own = client.post(
        "/api/v1/cases",
        headers=auth["manager"],
        json={"finding_id": b["finding_id"], "rationale": "Created by the approver"},
    ).json()
    r = client.post(
        "/api/v1/cases/batch-approve",
        headers=auth["manager"],
        json={"case_ids": [good["id"], own["id"], str(uuid.uuid4())], "note": "Batch engagement"},
    ).json()
    assert [x["case_id"] for x in r["approved"]] == [good["id"]]
    reasons = {x["case_id"]: x["reason"] for x in r["skipped"]}
    assert "creator" in reasons[own["id"]] and len(reasons) == 2


def test_identity_retraction_flags_dependent_findings_and_cases(
    client: TestClient, auth: dict, world: World
) -> None:
    ref = world.scenarios["missing_one"][0]
    f = next(x for x in findings(client, auth["manager"], employer=ref, rule="FIL-001"))
    case = client.post(
        "/api/v1/cases",
        headers=auth["officer"],
        json={"finding_id": f["finding_id"], "rationale": "Missing return"},
    ).json()
    client.post(f"/api/v1/cases/{case['id']}/approve", headers=auth["manager"], json={"note": "ok go"})
    matches = client.get(
        "/api/v1/identity-matches", headers=auth["steward"], params={"status": "auto_linked"}
    ).json()
    m = next(x for x in matches if x["employer_ref"] == ref)
    r = client.post(
        f"/api/v1/identity-matches/{m['id']}/decision",
        headers=auth["steward"],
        json={"decision": "retract", "reason": "Linked to the wrong taxpayer record"},
    )
    assert r.status_code == 200, r.text
    affected = r.json()
    assert f["finding_ref"] in affected["findings"] and case["case_ref"] in affected["cases"]
    after = client.get(f"/api/v1/risks/{f['finding_id']}", headers=auth["manager"]).json()
    assert after["flags"]["data_hold"] and "identity_retracted" in after["holds"]
    assert after["allowed_next_action"] == "data_review"
    c = client.get(f"/api/v1/cases/{case['id']}", headers=auth["manager"]).json()
    assert c["outward_permitted"] is False and "identity_unverified" in c["outward_blockers"]


def test_rule_change_is_governed_and_old_scores_stay_reproducible(
    client: TestClient, auth: dict, world: World
) -> None:
    old = _open_finding(client, auth, rule="PAY-002")
    rule = client.get("/api/v1/rules/PAY-002", headers=auth["analyst"]).json()
    current = next(v for v in rule["versions"] if v["status"] == "active")
    new_def = copy.deepcopy(current["definition"])
    new_def["version"] = "1.1.0"
    new_def["signal"]["likelihood"]["base"] = 3
    bad = copy.deepcopy(new_def)
    bad["conditions"] = [{"field": "payment_late_days", "op": "gt", "value": "0; DROP TABLE"}]
    assert (
        client.post("/api/v1/rules/validate", headers=auth["analyst"], json={"definition": bad}).json()[
            "valid"
        ]
        is False
    )
    assert (
        client.post(
            "/api/v1/rules", headers=auth["manager"], json={"definition": new_def, "change_note": "x" * 5}
        ).status_code
        == 403
    )
    drafted = client.post(
        "/api/v1/rules",
        headers=auth["analyst"],
        json={"definition": new_def, "change_note": "Raise base likelihood"},
    ).json()
    vid = drafted["id"]
    assert client.post(f"/api/v1/rules/versions/{vid}/submit", headers=auth["analyst"]).status_code == 409
    bt = client.post(
        f"/api/v1/rules/versions/{vid}/backtest",
        headers=auth["analyst"],
        json={"as_of": AS_OF, "period_from": "2025-09", "period_to": "2026-08"},
    ).json()
    assert bt["candidate"]["findings"] == bt["active"]["findings"] and bt["compared_with"] == "PAY-002@1.0.0"
    assert client.post(f"/api/v1/rules/versions/{vid}/submit", headers=auth["analyst"]).status_code == 200
    one = client.post(
        f"/api/v1/rules/versions/{vid}/approve",
        headers=auth["manager"],
        json={"note": "Reviewed impact", "as_role": "compliance_manager"},
    ).json()
    assert one["status"] == "pending_approval" and one["approvals"][0]["signature"]
    assert (
        client.post(
            f"/api/v1/rules/versions/{vid}/approve",
            headers=auth["manager2"],
            json={"note": "again", "as_role": "compliance_manager"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/rules/versions/{vid}/approve",
            headers=auth["manager"],
            json={"note": "both hats", "as_role": "legal_approver"},
        ).status_code
        == 403
    )
    two = client.post(
        f"/api/v1/rules/versions/{vid}/approve",
        headers=auth["legal"],
        json={"note": "Legal basis unchanged", "as_role": "legal_approver"},
    ).json()
    assert two["status"] == "approved"
    act = client.post(
        f"/api/v1/rules/versions/{vid}/activate",
        headers=auth["manager2"],
        json={"reason": "Approved recalibration"},
    )
    assert act.status_code == 200 and act.json()["status"] == "active"
    diff = client.get(
        "/api/v1/rules/PAY-002/diff",
        headers=auth["analyst"],
        params={"from_version": "1.0.0", "to_version": "1.1.0"},
    ).json()
    assert {"path": "signal.likelihood.base", "change": "changed", "from": 2, "to": 3} in diff["changes"]

    run = client.post(
        "/api/v1/rules/evaluations",
        headers=auth["manager"],
        json={"as_of": AS_OF, "period_from": "2025-09", "period_to": "2026-08"},
    ).json()
    assert run["reused"] is False and "PAY-002@1.1.0" in run["rule_versions"]
    old_after = client.get(f"/api/v1/risks/{old['finding_id']}", headers=auth["manager"]).json()
    assert old_after["superseded_by"] and old_after["status"] == "withdrawn"
    assert (
        client.post(f"/api/v1/risks/{old['finding_id']}/reproduce", headers=auth["manager"]).json()[
            "reproduced"
        ]
        is True
    )
    new = findings(client, auth["manager"], rule="PAY-002", q=old["subject"]["id"], period=old["tax_period"])
    assert new and new[0]["rule"]["version"] == "1.1.0" and new[0]["indicators"]["likelihood"] == 3
    rb = client.post(
        "/api/v1/rules/PAY-002/rollback", headers=auth["manager"], json={"reason": "Back to 1.0.0"}
    )
    assert rb.status_code == 200 and rb.json()["version"] == "1.0.0"
    assert (
        client.post(
            "/api/v1/rules/evaluations",
            headers=auth["manager"],
            json={"as_of": AS_OF, "period_from": "2025-09", "period_to": "2026-08"},
        ).status_code
        == 201
    )
    revived = client.get(f"/api/v1/risks/{old['finding_id']}", headers=auth["manager"]).json()
    assert revived["status"] == "review_required" and revived["superseded_by"] is None
    current = findings(
        client, auth["manager"], rule="PAY-002", q=old["subject"]["id"], period=old["tax_period"]
    )
    assert [f["rule"]["version"] for f in current] == ["1.0.0"]


def test_legal_versions_need_independent_approval(client: TestClient, auth: dict) -> None:
    body = {
        "code": "PAYE_EMPLOYER_MONTHLY_RETURN",
        "version": "2030.1-SYN",
        "instrument_code": "NS-TACL-2023",
        "provision_ref": "SYNTHETIC test provision",
        "effective_from": "2030-01-01",
        "parameters": {"due_day_of_following_month": 12},
    }
    assert client.post("/api/v1/legal/versions", headers=auth["officer"], json=body).status_code == 403
    v = client.post("/api/v1/legal/versions", headers=auth["legal"], json=body).json()
    assert v["status"] == "pending_approval"
    assert (
        client.post(
            f"/api/v1/legal/versions/{v['id']}/approve", headers=auth["legal"], json={"note": "self approval"}
        ).status_code
        == 403
    )
    same_start = {**body, "version": "2026.9-SYN", "effective_from": "2026-01-01"}
    assert client.post("/api/v1/legal/versions", headers=auth["analyst"], json=same_start).status_code == 409
    # Pending versions are not in force: 2030 periods still resolve to the approved 2026 version.
    still = client.get(
        "/api/v1/legal/resolve",
        headers=auth["analyst"],
        params={"code": "PAYE_EMPLOYER_MONTHLY_RETURN", "period": "2030-02"},
    ).json()
    assert still["approved_version"]["version"] == "2026.1-SYN"


def test_programme_cohorts_and_evaluation(client: TestClient, auth: dict) -> None:
    p = client.post(
        "/api/v1/programmes",
        headers=auth["analyst"],
        json={
            "code": "PAYE-MINNA-T1",
            "name": "Minna reminders",
            "objective": "Improve on-time PAYE filing",
            "population": {"lga_codes": ["CHA", "BOS"]},
            "denominator_definition": "Obligated Minna employers",
            "baseline_from": "2025-09",
            "baseline_to": "2026-02",
            "evaluation_from": "2026-03",
            "evaluation_to": "2026-08",
            "intervention": "Approved reminders",
            "target": "+5 percentage points",
        },
    ).json()
    assert p["members"].get("intervention") and p["members"].get("comparison")
    assert client.post(f"/api/v1/programmes/{p['id']}/approve", headers=auth["manager"]).status_code == 200
    ev = client.post(f"/api/v1/programmes/{p['id']}/evaluate", headers=auth["analyst"]).json()
    for g in ("intervention", "comparison"):
        for w in ("baseline", "evaluation"):
            m = ev["groups"][g][w]
            assert m["denominator"] and m["window"] and m["completeness"] is not None
    assert "difference_in_differences" in ev and "Denominator" in ev["method"]


def test_report_export_requires_permission_and_purpose(client: TestClient, auth: dict) -> None:
    url = "/api/v1/reports/compliance_by_lga"
    assert client.get(url, headers=auth["exec"], params={"format": "csv"}).status_code == 403
    r = client.get(
        url, headers={**auth["exec"], "X-Purpose": "management_reporting"}, params={"format": "csv"}
    )
    assert r.status_code == 200 and r.text.startswith("#") and "filing_denominator" in r.text
    assert client.get(url, headers=auth["analyst"], params={"format": "csv"}).status_code == 403
    summary = client.get("/api/v1/reports/findings_register", headers=auth["exec"]).json()
    assert summary["rows"] and "subject" not in summary["rows"][0]  # executives see aggregates only
