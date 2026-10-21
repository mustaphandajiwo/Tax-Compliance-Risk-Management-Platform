"""PRD §16 controls: access isolation, unauthorised transitions, four-eyes, export masking,
confidence gating and audit logging of access."""

import pytest

from taxcris.testing import load_small, taxpayer_id


@pytest.fixture
def loaded(env):
    load_small(env)
    load_small(env, tenant="KW")
    for t in ("NI", "KW"):
        r = env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst", t))
        assert r.json()["status"] == "completed"
    return env


def test_no_cross_tenant_taxpayer_access(loaded):
    env = loaded
    ni_tp = taxpayer_id(env, "Kpada", tenant="NI")
    kw_tp = taxpayer_id(env, "Kpada", tenant="KW")
    assert ni_tp != kw_tp
    assert env.client.get(f"/v1/taxpayers/{ni_tp}", headers=env.h("analyst", "KW")).status_code == 404
    assert env.client.get(f"/v1/taxpayers/{kw_tp}", headers=env.h("analyst", "NI")).status_code == 404
    ni_ids = {t["id"] for t in env.client.get("/v1/taxpayers", params={"limit": 500}, headers=env.h("analyst")).json()["items"]}
    assert kw_tp not in ni_ids
    ni_alert = env.client.get("/v1/alerts", headers=env.h("analyst")).json()["items"][0]
    for path in (f"/v1/alerts/{ni_alert['id']}", f"/v1/risk-assessments/{ni_alert['assessment_id']}"):
        assert env.client.get(path, headers=env.h("analyst", "KW")).status_code == 404
    r = env.client.post(f"/v1/alerts/{ni_alert['id']}/triage", json={"decision": "dismiss", "reason": "cross tenant"},
                        headers=env.h("analyst", "KW"))
    assert r.status_code == 404
    assert all(e["action"] != "alert.dismissed" for e in
               env.client.get("/v1/audit-events", headers=env.h("security")).json()["items"])


def test_same_identifier_hashes_differ_per_tenant(loaded):
    from sqlalchemy import select

    from taxcris import db as dbmod
    from taxcris.models import IdentityLink

    with dbmod.session_factory()() as db:
        hashes = {}
        for link in db.execute(select(IdentityLink).where(IdentityLink.masked_value == "********0001")).scalars():
            hashes.setdefault(link.tenant_id, link.hashed_identifier)
    assert len(set(hashes.values())) == 2


def test_role_permissions_denied_and_audited(loaded):
    env = loaded
    c = env.client
    assert c.get("/v1/taxpayers", headers=env.h("exec")).status_code == 403         # executive: no raw records
    assert c.get("/v1/exports/alerts.csv", headers=env.h("exec")).status_code == 403
    assert c.get("/v1/audit-events", headers=env.h("analyst")).status_code == 403
    assert c.post("/v1/imports", json={}, headers=env.h("officer")).status_code in (403, 422)
    assert c.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("officer")).status_code == 403
    denied = c.get("/v1/audit-events", params={"outcome": "denied"}, headers=env.h("security")).json()["items"]
    paths = {e["resource_id"] for e in denied}
    assert "GET /v1/exports/alerts.csv" in paths and "GET /v1/taxpayers" in paths


def test_unauthenticated_requests_rejected(env):
    assert env.client.get("/v1/taxpayers").status_code == 401
    assert env.client.get("/v1/taxpayers", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert env.client.post("/v1/auth/login", json={"email": "analyst@niger.test", "password": "wrong"}).status_code == 401


def test_record_export_is_masked_and_logged(loaded):
    env = loaded
    r = env.client.get("/v1/exports/alerts.csv", headers=env.h("manager"))
    assert r.status_code == 200
    assert "SYN-T000000" not in r.text and "********000" in r.text
    ev = env.client.get("/v1/audit-events", params={"action": "export.alerts"}, headers=env.h("security")).json()["items"]
    assert ev and ev[0]["details"]["masked"] is True


def test_taxpayer_access_is_logged(loaded):
    env = loaded
    tid = taxpayer_id(env, "Kpada")
    env.client.get(f"/v1/taxpayers/{tid}", headers=env.h("officer"))
    ev = env.client.get("/v1/audit-events", params={"action": "taxpayer.view", "resource_id": tid},
                        headers=env.h("security")).json()["items"]
    assert ev and ev[0]["actor_role"] == "compliance_officer"


def test_unauthorised_and_invalid_case_transitions(loaded):
    env = loaded
    c = env.client
    alert = c.get("/v1/alerts", params={"status": "open"}, headers=env.h("analyst")).json()["items"][0]
    c.post(f"/v1/alerts/{alert['id']}/triage", json={"decision": "confirm", "reason": "Reviewed evidence"}, headers=env.h("analyst"))
    case = c.post("/v1/cases", json={"alert_id": alert["id"], "justification": "Open it"}, headers=env.h("analyst")).json()
    url = f"/v1/cases/{case['id']}/actions"

    def act(h, action, payload=None, just="Because reasons"):
        return c.post(url, json={"action": action, "justification": just, "payload": payload or {}}, headers=env.h(h))

    assert act("officer", "approve_proposal").status_code == 403                 # wrong role
    assert act("manager", "approve_proposal").status_code == 409                 # wrong state
    assert act("analyst", "submit_proposal", {"intervention_type": "audit_referral"}).status_code == 409  # referral path only
    assert act("analyst", "submit_proposal", {"intervention_type": "fine_them"}).status_code == 409
    assert act("analyst", "submit_proposal", {"intervention_type": "desk_verification"}).status_code == 200
    # Proposer cannot approve own proposal even with approval rights
    own = c.post("/v1/cases", json={"alert_id": alert["id"], "justification": "x" * 6}, headers=env.h("manager"))
    assert own.status_code == 409
    assert act("manager", "approve_proposal").status_code == 200
    assert act("audit", "close", {"disposition": "resolved_compliant"}).status_code == 403
    assert act("manager", "close", {"disposition": "made_up"}).status_code == 409
    detail = c.get(f"/v1/cases/{case['id']}", headers=env.h("officer")).json()
    assert detail["status"] == "approved"
    assert set(detail["available_actions"]) == {"start_work"}


def test_manager_cannot_approve_own_proposal(loaded):
    env = loaded
    c = env.client
    alert = c.get("/v1/alerts", params={"status": "open"}, headers=env.h("manager")).json()["items"][1]
    c.post(f"/v1/alerts/{alert['id']}/triage", json={"decision": "confirm", "reason": "Reviewed evidence"}, headers=env.h("manager"))
    case = c.post("/v1/cases", json={"alert_id": alert["id"], "justification": "Open it"}, headers=env.h("manager")).json()
    url = f"/v1/cases/{case['id']}/actions"
    c.post(url, json={"action": "submit_proposal", "justification": "Reminder", "payload": {"intervention_type": "filing_reminder"}},
           headers=env.h("manager"))
    r = c.post(url, json={"action": "approve_proposal", "justification": "Self approve"}, headers=env.h("manager"))
    assert r.status_code == 403
    assert c.post(url, json={"action": "approve_proposal", "justification": "Second pair of eyes"},
                  headers=env.h("manager2")).status_code == 200


def test_risk_model_cannot_be_approved_by_author(env):
    c = env.client
    m = c.post("/v1/risk-models", json={"name": "v2", "weights": {"registration": 0.1, "filing": 0.4, "reporting": 0.2,
                                                                  "payment": 0.3}}, headers=env.h("analyst")).json()
    c.post(f"/v1/risk-models/{m['id']}/submit", headers=env.h("analyst"))
    assert c.post(f"/v1/risk-models/{m['id']}/approve", json={"reason": "my own"}, headers=env.h("analyst")).status_code == 403
    assert c.post(f"/v1/risk-models/{m['id']}/approve", json={"reason": "Back-tested"}, headers=env.h("analyst2")).status_code == 200
    models = {x["version"]: x["status"] for x in c.get("/v1/risk-models", headers=env.h("analyst")).json()}
    assert models == {2: "approved", 1: "retired"}


def test_low_confidence_alert_routes_to_data_verification(env):
    """Stale feeds: adverse prioritisation suppressed; only data correction may be proposed."""
    from taxcris.testing import small_dataset

    ds = small_dataset()
    env.import_records("taxpayers", ds["taxpayers"], extracted_at="2026-06-01")
    env.import_records("returns", ds["returns"][:12], extracted_at="2026-06-01")
    env.import_records("payments", ds["payments"][:12], extracted_at="2026-06-01")
    env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    dv = env.client.get("/v1/alerts", params={"status": "data_verification"}, headers=env.h("analyst")).json()["items"]
    assert dv
    a = dv[0]
    detail = env.client.get(f"/v1/risk-assessments/{a['assessment_id']}", headers=env.h("analyst")).json()
    assert detail["suppressed"] and detail["suppression_reason"]
    r = env.client.post(f"/v1/alerts/{a['id']}/triage", json={"decision": "confirm", "reason": "Looks bad"}, headers=env.h("analyst"))
    assert r.status_code == 409
    esc = env.client.post(f"/v1/alerts/{a['id']}/triage", json={"decision": "escalate", "reason": "Needs data steward"},
                          headers=env.h("analyst"))
    assert esc.status_code == 200
    case = env.client.post("/v1/cases", json={"alert_id": a["id"], "justification": "Verify data"}, headers=env.h("analyst")).json()
    url = f"/v1/cases/{case['id']}/actions"
    bad = env.client.post(url, json={"action": "submit_proposal", "justification": "Chase them",
                                     "payload": {"intervention_type": "payment_follow_up"}}, headers=env.h("analyst"))
    assert bad.status_code == 409
    ok = env.client.post(url, json={"action": "submit_proposal", "justification": "Refresh feeds",
                                    "payload": {"intervention_type": "correct_data"}}, headers=env.h("analyst"))
    assert ok.status_code == 200
