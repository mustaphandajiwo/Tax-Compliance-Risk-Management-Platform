"""Pure scoring engine: renormalisation, confidence gating, safeguards, determinism."""

import copy

from taxcris.domain.scoring import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, evaluate, output_hash

FRESH = {"taxpayers": "2026-10-18", "returns": "2026-10-18", "payments": "2026-10-18", "employments": None}


def base_inputs(**over):
    inp = {
        "engine_version": "signals-1.0.0",
        "as_of": "2026-10-21",
        "jurisdiction": "NI",
        "tax_type": "PAYE",
        "scope": "2026",
        "taxpayer": {"id": "t1", "taxpayer_type": "business", "registration_status": "registered", "tax_residence": "NI",
                     "operating_status": "active", "closed_on": None, "source": "SRC:1"},
        "obligations": [],
        "returns": [],
        "payments": [],
        "identity": {"identifier_count": 1, "min_match_confidence": 1.0, "pending_merge_confidence": None},
        "feeds": dict(FRESH),
    }
    inp.update(over)
    return inp


def ob(period, due, oid=None):
    return {"id": oid or f"ob-{period}", "period": period, "due_date": due, "extension_until": None,
            "rule_code": "PAYE_MONTHLY_REMITTANCE", "rule_version": 2}


def ret(period, filed, income="1000000.00", amount="70000.00"):
    return {"id": f"r-{period}", "period": period, "filing_date": filed, "reported_income": income,
            "reported_amount": amount, "source": "SRC"}


def pay(period, date_, amount="70000.00", status="allocated"):
    return {"id": f"p-{period}-{amount}", "period": period, "amount": amount, "payment_date": date_,
            "allocation_status": status, "source": "SRC"}


def run(inp, **th):
    return evaluate(inp, DEFAULT_WEIGHTS, {**DEFAULT_THRESHOLDS, **th})


def test_compliant_taxpayer_scores_zero_and_excludes_non_applicable_dimensions():
    inp = base_inputs(obligations=[ob("2026-01", "2026-02-10")], returns=[ret("2026-01", "2026-02-05")],
                      payments=[pay("2026-01", "2026-02-05")])
    r = run(inp)
    assert r["score"] == 0
    assert r["signals"] == []
    # reporting needs ≥3 periods of history, so it is excluded and weights renormalised
    assert r["dimension_scores"]["reporting"] is None
    assert set(r["weights_applied"]) == {"registration", "filing", "payment"}
    assert abs(sum(r["weights_applied"].values()) - 1) < 1e-5


def test_unregistered_entity_only_registration_applies():
    inp = base_inputs(taxpayer={**base_inputs()["taxpayer"], "registration_status": "unregistered"})
    r = run(inp)
    assert [s["rule_id"] for s in r["signals"]] == ["REG-001"]
    assert r["weights_applied"] == {"registration": 1.0}
    assert r["score"] == 70


def test_unregistered_out_of_state_entity_is_not_flagged():
    tp = {**base_inputs()["taxpayer"], "registration_status": "unregistered", "tax_residence": "FC"}
    assert run(base_inputs(taxpayer=tp))["signals"] == []


def test_non_filing_raises_filing_and_payment_signals_with_links_to_legal_rule():
    inp = base_inputs(obligations=[ob("2026-08", "2026-09-10")])
    r = run(inp)
    codes = {s["rule_id"] for s in r["signals"]}
    assert codes == {"FIL-001", "PAY-003"}
    fil = next(s for s in r["signals"] if s["rule_id"] == "FIL-001")
    assert fil["evidence_ref"]["legal_rule"] == {"rule_code": "PAYE_MONTHLY_REMITTANCE", "rule_version": 2,
                                                 "deadline": "2026-09-10"}
    assert fil["confidence"] == 0.95
    assert r["flagged"]


def test_obligation_not_yet_due_makes_no_adverse_inference():
    r = run(base_inputs(obligations=[ob("2026-10", "2026-11-10")]))
    assert r["signals"] == [] and r["dimension_scores"]["filing"] is None


def test_stale_returns_feed_lowers_confidence_and_suppresses():
    feeds = {**FRESH, "returns": "2026-08-01", "payments": "2026-08-01"}
    r = run(base_inputs(obligations=[ob("2026-08", "2026-09-10")], feeds=feeds))
    fil = next(s for s in r["signals"] if s["rule_id"] == "FIL-001")
    assert fil["confidence"] == 0.3
    assert any(g["check"] == "returns_feed_freshness" and g["result"] == "fail" for g in fil["safeguards"])
    assert r["confidence"] < DEFAULT_THRESHOLDS["min_confidence"]
    assert r["suppressed"] and "data verification" in r["suppression_reason"]


def test_likely_duplicate_identity_is_suppressed_even_with_good_data():
    ident = {"identifier_count": 1, "min_match_confidence": 1.0, "pending_merge_confidence": 0.97}
    r = run(base_inputs(obligations=[ob("2026-08", "2026-09-10")], identity=ident))
    assert r["flagged"] and r["suppressed"]
    assert "duplicate" in r["suppression_reason"]


def test_shortfall_with_unallocated_payments_recommends_data_correction():
    inp = base_inputs(obligations=[ob("2026-01", "2026-02-10")], returns=[ret("2026-01", "2026-02-05")],
                      payments=[pay(None, "2026-02-05", status="unallocated")])
    r = run(inp)
    s = next(s for s in r["signals"] if s["rule_id"] == "PAY-001")
    assert s["recommended_action"] == "correct_data"
    assert s["confidence"] <= 0.4
    assert s["exposure"] == "70000.00"


def test_shortfall_exposure_and_severity():
    inp = base_inputs(obligations=[ob("2026-01", "2026-02-10")], returns=[ret("2026-01", "2026-02-05")],
                      payments=[pay("2026-01", "2026-02-05", amount="35000.00")])
    s = next(s for s in run(inp)["signals"] if s["rule_id"] == "PAY-001")
    assert s["exposure"] == "35000.00"
    assert s["severity"] == 70.0  # 40 + 60 × 50%


def test_within_tolerance_is_not_a_shortfall():
    inp = base_inputs(obligations=[ob("2026-01", "2026-02-10")], returns=[ret("2026-01", "2026-02-05")],
                      payments=[pay("2026-01", "2026-02-05", amount="67000.00")])
    assert not [s for s in run(inp)["signals"] if s["rule_id"] == "PAY-001"]


def _monthly_history(months, income_for):
    obs, rets = [], []
    for p in months:
        obs.append(ob(p, "2026-12-31"))  # due dates irrelevant to the reporting rule
        rets.append(ret(p, f"{p}-05", income=income_for(p), amount=f"{float(income_for(p)) * 0.07:.2f}"))
    return obs, rets


def test_income_deviation_is_a_hypothesis_with_exposure():
    months = [f"2026-{m:02d}" for m in range(1, 8)]
    obs, rets = _monthly_history(months, lambda p: "300000.00" if p == "2026-07" else "1000000.00")
    r = run(base_inputs(as_of="2026-07-20", obligations=obs[-1:], returns=rets))
    s = next(s for s in r["signals"] if s["rule_id"] == "REP-001")
    assert s["is_hypothesis"] is True
    assert s["recommended_action"] == "desk_verification"
    assert s["exposure"] == "49000.00"  # (1,000,000 − 300,000) × 7%


def test_seasonal_decline_is_suppressed_by_safeguard():
    months = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13) if (y, m) <= (2026, 7)]
    low = {"2025-07", "2026-07"}
    obs, rets = _monthly_history(months, lambda p: "400000.00" if p in low else "1000000.00")
    r = run(base_inputs(as_of="2026-07-20", obligations=[o for o in obs if o["period"] == "2026-07"], returns=rets))
    assert not [s for s in r["signals"] if s["rule_id"] == "REP-001"]


def test_evaluation_is_deterministic_and_input_order_independent_of_dict_copy():
    inp = base_inputs(obligations=[ob("2026-08", "2026-09-10"), ob("2026-01", "2026-02-10")],
                      returns=[ret("2026-01", "2026-02-20")], payments=[pay("2026-01", "2026-03-01", amount="10000.00")])
    a, b = run(inp), run(copy.deepcopy(inp))
    assert output_hash(a) == output_hash(b)
    assert a["score"] == b["score"]


def test_weights_change_changes_score_but_not_signals():
    inp = base_inputs(obligations=[ob("2026-08", "2026-09-10")], returns=[], payments=[])
    a = evaluate(inp, DEFAULT_WEIGHTS, DEFAULT_THRESHOLDS)
    b = evaluate(inp, {**DEFAULT_WEIGHTS, "filing": 0.6}, DEFAULT_THRESHOLDS)
    assert a["signals"] == b["signals"]
    assert b["score"] > a["score"]
