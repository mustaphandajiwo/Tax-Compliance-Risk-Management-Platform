"""PRD §21 first vertical slice and §4 Journeys A–D, driven through the HTTP API.

login → synthetic taxpayer import → taxpayer profile → obligation → risk signal → analyst review
→ approved case → dashboard metric — with no autonomous adverse decision anywhere.
"""

from taxcris.testing import load_small, taxpayer_id


def test_first_slice_end_to_end(env):
    c = env.client

    # Login (real credential check)
    tok = c.post("/v1/auth/login", json={"email": "analyst@niger.test", "password": "Demo-Pass-2026!"})
    assert tok.status_code == 200
    me = c.get("/v1/auth/me", headers={"Authorization": f"Bearer {tok.json()['access_token']}"}).json()
    assert me["role"] == "risk_analyst" and me["tenant"]["state_code"] == "NI"

    # Synthetic import, reconciled
    batches = load_small(env)
    assert all(b["reconciliation_status"] == "reconciled" for b in batches.values())

    # Risk run with the approved model → obligations + signals
    run = c.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst")).json()
    assert run["status"] == "completed" and run["model_version"] == 1 and run["dataset_hash"]

    # Taxpayer profile shows obligations from the versioned rule
    tid = taxpayer_id(env, "Gurara Building")
    profile = c.get(f"/v1/taxpayers/{tid}", headers=env.h("analyst")).json()
    overdue = [o for o in profile["obligations"] if o["status"] == "overdue"]
    assert overdue and all(o["rule_version"] == 2 for o in overdue)

    # Alert with explainable, traceable signal (Journey A)
    alerts = c.get("/v1/alerts", params={"status": "open"}, headers=env.h("analyst")).json()["items"]
    alert = next(a for a in alerts if a["taxpayer_id"] == tid)
    detail = c.get(f"/v1/risk-assessments/{alert['assessment_id']}", headers=env.h("analyst")).json()
    fil = next(s for s in detail["signals"] if s["rule_id"] == "FIL-001")
    assert fil["obligation_id"] in {o["id"] for o in overdue}
    assert fil["evidence_ref"]["legal_rule"]["rule_code"] == "PAYE_MONTHLY_REMITTANCE"
    assert detail["weights_applied"] and detail["confidence_components"].keys() == {
        "coverage", "timeliness", "matching_certainty", "evidence_reliability"}
    assert detail["inputs_hash"] and detail["model_version"] == 1

    # Reproducible score
    rep = c.post(f"/v1/risk-assessments/{detail['id']}/reproduce", headers=env.h("analyst")).json()
    assert rep["reproducible"] is True

    # Analyst review: confirm with reason, open case
    assert c.post(f"/v1/alerts/{alert['id']}/triage", json={"decision": "confirm", "reason": "Deadlines passed, feeds fresh"},
                  headers=env.h("analyst")).json()["status"] == "confirmed"
    case = c.post("/v1/cases", json={"alert_id": alert["id"], "justification": "Non-filing since March"},
                  headers=env.h("analyst"))
    assert case.status_code == 201, case.text
    case = case.json()
    assert case["status"] == "open" and "submit_proposal" in case["available_actions"]
    dup = c.post("/v1/cases", json={"alert_id": alert["id"], "justification": "again please"}, headers=env.h("analyst"))
    assert dup.status_code == 409

    # Journey B: proposal → manager approval (different person) → officer works → close
    def act(handle, action, justification, **payload):
        r = c.post(f"/v1/cases/{case['id']}/actions", json={"action": action, "justification": justification, "payload": payload},
                   headers=env.h(handle))
        return r

    assert act("analyst", "submit_proposal", "Reminder is proportionate", intervention_type="filing_reminder").status_code == 200
    r = act("manager", "approve_proposal", "Evidence sufficient", assignee_id=env.user_id("officer"))
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["assignee_id"] == env.user_id("officer")
    assert act("officer2", "start_work", "Not my case though").status_code == 403
    assert act("officer", "start_work", "Reminder letter issued").json()["status"] == "in_progress"
    assert act("officer", "record_contact", "Called the payroll desk", channel="phone").status_code == 200
    closed = act("manager", "close", "Returns filed", disposition="resolved_compliant").json()
    assert closed["status"] == "closed" and not closed["sla_breached"]
    assert [a["action"] for a in closed["actions"]] == [
        "create", "submit_proposal", "approve_proposal", "start_work", "record_contact", "close"]
    assert all(a["justification"] for a in closed["actions"])

    # Dashboard metric with definitions, numerator/denominator, freshness (Journey D)
    m = c.get("/v1/metrics", params={"period": "2026", "tax_type": "PAYE"}, headers=env.h("exec")).json()
    by_key = {x["key"]: x for x in m["metrics"]}
    tf = by_key["timely_filing_rate"]
    assert tf["denominator"] > 0 and tf["value"] == round(tf["numerator"] / tf["denominator"], 4)
    assert tf["definition"] and tf["freshness"]["returns"] == "2026-10-18" and tf["coverage"] == 1.0
    assert by_key["cases_within_sla"]["numerator"] == 1 and by_key["cases_within_sla"]["denominator"] == 1
    assert m["breakdowns"]["timely_filing_by_lga"]
    brief = c.get("/v1/exports/management-brief.csv", params={"period": "2026"}, headers=env.h("exec"))
    assert brief.status_code == 200 and brief.text.startswith("metric,label,value")


def test_metric_reconciles_to_source(env):
    """Timely filing figure equals a hand count from the fixture (3 filers, B2 stops in 2026-03)."""
    load_small(env)
    env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    m = env.client.get("/v1/metrics", params={"period": "2026", "tax_type": "PAYE"}, headers=env.h("exec")).json()
    tf = {x["key"]: x for x in m["metrics"]}["timely_filing_rate"]
    # Jan–Sep 2026 due before 2026-10-21: 9 months × 3 eligible employers; B2 misses Mar–Sep (7).
    assert (tf["numerator"], tf["denominator"]) == (20, 27)
    pay = {x["key"]: x for x in m["metrics"]}["payment_compliance_rate"]
    # Filed obligations: B1 9 + B2 2 + B3 9 = 20; B3 underpays all 9 → 11 compliant.
    assert (pay["numerator"], pay["denominator"]) == (11, 20)


def test_audit_referral_rejection_returns_case_to_review(env):
    """Journey C and backlog story: rejecting an audit referral requires a reason, is immutable, returns to review."""
    load_small(env)
    env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    tid = taxpayer_id(env, "Zuma Logistics")
    alert = next(a for a in env.client.get("/v1/alerts", headers=env.h("manager")).json()["items"] if a["taxpayer_id"] == tid)
    assert "PAY-001" in alert["reason_codes"]
    env.client.post(f"/v1/alerts/{alert['id']}/triage", json={"decision": "escalate", "reason": "Material shortfall"},
                    headers=env.h("analyst"))
    case = env.client.post("/v1/cases", json={"alert_id": alert["id"], "justification": "Escalated shortfall"},
                           headers=env.h("manager")).json()
    url = f"/v1/cases/{case['id']}/actions"
    no_mat = env.client.post(url, json={"action": "refer_audit", "justification": "Large", "payload": {}}, headers=env.h("manager"))
    assert no_mat.status_code == 409
    ok = env.client.post(url, json={"action": "refer_audit", "justification": "Material over 9 months",
                                    "payload": {"materiality": "Shortfall 360,000"}}, headers=env.h("manager"))
    assert ok.json()["status"] == "audit_referral_pending"
    # An analyst cannot decide audits; the audit manager can — with a reason.
    assert env.client.post(url, json={"action": "reject_audit", "justification": "nope nope"},
                           headers=env.h("analyst")).status_code == 403
    no_reason = env.client.post(url, json={"action": "reject_audit", "justification": ""}, headers=env.h("audit"))
    assert no_reason.status_code == 422
    rej = env.client.post(url, json={"action": "reject_audit", "justification": "Capacity; try payment follow-up first"},
                          headers=env.h("audit")).json()
    assert rej["status"] == "open" and rej["interventions"][-1]["status"] == "rejected"
    ev = env.client.get("/v1/audit-events", params={"action": "case.reject_audit"}, headers=env.h("security")).json()["items"]
    assert ev and ev[0]["details"]["justification"].startswith("Capacity")
