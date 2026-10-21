"""Legal correctness: deadlines, eligibility, historical rule-version selection, dual approval."""

from datetime import date

from taxcris.domain.obligations import compute_due_date, period_bounds, periods_for
from taxcris.testing import load_small, taxpayer_id


def test_deadline_types():
    assert compute_due_date({"type": "days_after_period_end", "days": 10}, date(2026, 1, 31)) == date(2026, 2, 10)
    assert compute_due_date({"type": "days_after_period_end", "days": 10}, date(2024, 2, 29)) == date(2024, 3, 10)
    assert compute_due_date({"type": "fixed_date_following_year", "month": 3, "day": 31}, date(2025, 12, 31)) == date(2026, 3, 31)


def test_periods():
    assert periods_for("monthly", "2026")[0] == "2026-01" and len(periods_for("monthly", "2026")) == 12
    assert periods_for("monthly", "2026-03") == ["2026-03"]
    assert periods_for("annual", "2025") == ["2025"]
    assert period_bounds("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def _rule(env, **over):
    body = {"rule_code": "PAYE_MONTHLY_REMITTANCE", "title": "Test", "jurisdiction": "Niger State", "tax_type": "PAYE",
            "frequency": "monthly", "eligibility": {"taxpayer_type": "business", "is_employer": True},
            "deadline": {"type": "days_after_period_end", "days": 15}, "citation": "TEST ONLY",
            "valid_from": "2026-06-01"}
    body.update(over)
    r = env.client.post("/v1/legal-rules", json=body, headers=env.h("legal"))
    assert r.status_code == 201, r.text
    return r.json()


def test_historical_period_selects_rule_version_in_force(env):
    load_small(env)
    new = _rule(env)
    assert new["version"] == 3  # two seeded versions already exist
    assert env.client.post(f"/v1/legal-rules/{new['id']}/submit", headers=env.h("legal")).status_code == 200
    r = env.client.post(f"/v1/legal-rules/{new['id']}/approve", json={"reason": "Counsel signed off"}, headers=env.h("legal2"))
    assert r.status_code == 200, r.text

    run = env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    assert run.status_code == 202 and run.json()["status"] == "completed", run.text
    tp = env.client.get(f"/v1/taxpayers/{taxpayer_id(env, 'Kpada')}", headers=env.h("analyst")).json()
    by_period = {o["period"]: o for o in tp["obligations"]}
    assert by_period["2026-05"]["rule_version"] == 2 and by_period["2026-05"]["due_date"] == "2026-06-10"
    assert by_period["2026-06"]["rule_version"] == 3 and by_period["2026-06"]["due_date"] == "2026-07-15"

    run25 = env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2025"}, headers=env.h("analyst"))
    assert run25.json()["status"] == "completed"
    tp = env.client.get(f"/v1/taxpayers/{taxpayer_id(env, 'Kpada')}", headers=env.h("analyst")).json()
    assert {o["period"]: o["rule_version"] for o in tp["obligations"]}["2025-12"] == 1

    # Rollback: retiring v3 reinstates v2 for later periods.
    r = env.client.post(f"/v1/legal-rules/{new['id']}/retire", json={"reason": "Rolled back pending review"}, headers=env.h("legal2"))
    assert r.status_code == 200
    rules = {(x["rule_code"], x["version"]): x for x in env.client.get("/v1/legal-rules", headers=env.h("legal")).json()}
    assert rules[("PAYE_MONTHLY_REMITTANCE", 2)]["valid_to"] is None


def test_rule_requires_second_officer(env):
    new = _rule(env)
    env.client.post(f"/v1/legal-rules/{new['id']}/submit", headers=env.h("legal"))
    r = env.client.post(f"/v1/legal-rules/{new['id']}/approve", json={"reason": "self approval"}, headers=env.h("legal"))
    assert r.status_code == 403
    denied = env.client.get("/v1/audit-events", params={"outcome": "denied", "action": "legal_rule"}, headers=env.h("security"))
    assert denied.json()["total"] == 1


def test_rule_sandbox_preview(env):
    new = _rule(env)
    r = env.client.post(f"/v1/legal-rules/{new['id']}/test", json={"period": "2026-06"}, headers=env.h("legal"))
    assert r.json()["results"] == [{"period": "2026-06", "due_date": "2026-07-15", "this_version_valid": True,
                                    "version_in_force": 2}]


def test_closed_and_unregistered_taxpayers_get_no_obligations(env):
    load_small(env)
    env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    closed = env.client.get(f"/v1/taxpayers/{taxpayer_id(env, 'Edu Rice')}", headers=env.h("analyst")).json()
    assert closed["obligations"] == []
    unreg = env.client.get(f"/v1/taxpayers/{taxpayer_id(env, 'Tagwai')}", headers=env.h("analyst")).json()
    assert unreg["obligations"] == []
    assert unreg["assessments"][0]["reason_codes"] == ["REG-001"]


def test_obligation_status_reflects_filing(env):
    load_small(env)
    env.client.post("/v1/risk-runs", json={"tax_type": "PAYE", "period": "2026"}, headers=env.h("analyst"))
    nf = env.client.get(f"/v1/taxpayers/{taxpayer_id(env, 'Gurara Building')}", headers=env.h("analyst")).json()
    st = {o["period"]: o["status"] for o in nf["obligations"]}
    assert st["2026-02"] == "filed" and st["2026-03"] == "overdue" and st["2026-10"] == "open"
