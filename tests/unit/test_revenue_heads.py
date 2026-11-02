"""Revenue heads: obligation patterns, due dates, pack validation and the head-agnostic rules."""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from risk_engine import evaluate, load_pilot_pack
from risk_engine.heads import PATTERNS, obligation_codes, required_parameters, split_code
from taxrisk_api.jurisdiction import Pack, packs_dir
from taxrisk_api.services.legal import head_due, obligation_spec, period_bounds

LAGOS = ZoneInfo("Africa/Lagos")
RULES = {r.id: r for r in load_pilot_pack()}


def test_codes_follow_the_pattern() -> None:
    assert obligation_codes("LUC", "annual_demand") == ["LUC_DEMAND"]
    assert obligation_codes("WHT", "monthly_return_payment") == ["WHT_MONTHLY_RETURN", "WHT_MONTHLY_PAYMENT"]
    assert split_code("PITDA_ANNUAL_RETURN") == ("PITDA", "ANNUAL_RETURN")
    assert required_parameters("CGT_TRANSACTION") == ("days_after_transaction",)
    assert split_code("NOPE") is None
    # PAYE codes keep their own fixed specification
    assert obligation_spec("PAYE_EMPLOYER_REMITTANCE")["tax_type"] == "PAYE"  # type: ignore[index]
    assert obligation_spec("MVL_RENEWAL") == {
        "tax_type": "MVL",
        "obligation_type": "renewal",
        "pattern": "licence_renewal",
        "required": ["grace_days"],
    }
    assert set(PATTERNS) == {
        "monthly_return_payment",
        "annual_return_payment",
        "annual_demand",
        "licence_renewal",
        "transaction",
        "annual_levy",
    }


def test_annual_periods() -> None:
    assert period_bounds("2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert period_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))


@pytest.mark.parametrize(
    ("code", "period", "params", "event", "expected"),
    [
        (
            "WHT_MONTHLY_RETURN",
            "2026-03",
            {"due_day_of_following_month": 21},
            None,
            "2026-04-21T22:59:59+00:00",
        ),
        ("PITDA_ANNUAL_RETURN", "2025", {"due_month": 3, "due_day": 31}, None, "2026-03-31T22:59:59+00:00"),
        ("DEVL_ANNUAL_LEVY", "2026", {"due_month": 2, "due_day": 30}, None, "2026-02-28T22:59:59+00:00"),
        (
            "LUC_DEMAND",
            "2025",
            {"payment_days_after_service": 45},
            date(2025, 2, 15),
            "2025-04-01T22:59:59+00:00",
        ),
        ("MVL_RENEWAL", "2026", {"grace_days": 14}, date(2026, 5, 28), "2026-06-11T22:59:59+00:00"),
        (
            "CGT_TRANSACTION",
            "2026-04",
            {"days_after_transaction": 30},
            date(2026, 4, 3),
            "2026-05-03T22:59:59+00:00",
        ),
    ],
)
def test_due_dates(code: str, period: str, params: dict, event: date | None, expected: str) -> None:
    due = head_due(code, period, params, LAGOS, event)
    assert due is not None and due.isoformat() == expected


def test_event_patterns_have_no_due_date_without_the_event() -> None:
    # An unserved demand creates no payment obligation; an unrecorded expiry no renewal deadline.
    assert head_due("LUC_DEMAND", "2025", {"payment_days_after_service": 45}, LAGOS) is None
    assert head_due("BPR_RENEWAL", "2025", {"grace_days": 31}, LAGOS) is None


def _pack(**changes: Any) -> dict:
    raw = json.loads((packs_dir() / "demo" / "pack.json").read_text())
    raw.update(changes)
    return raw


def test_land_use_charge_is_the_property_regime_and_tenement_rates_are_reserved() -> None:
    assert Pack.model_validate(_pack()).property_regime == "land_use_charge"
    with pytest.raises(ValidationError, match="tenement_rate"):
        Pack.model_validate(_pack(property_regime="tenement_rate"))
    with pytest.raises(ValidationError, match="property head"):
        Pack.model_validate(_pack(property_regime="none"))


def test_pack_rejects_unknown_patterns_and_missing_parameters() -> None:
    raw = _pack()
    raw["tax_heads"][0]["pattern"] = "quarterly_magic"
    with pytest.raises(ValidationError, match="unknown pattern"):
        Pack.model_validate(raw)
    raw = _pack()
    for v in raw["legal_versions"]:
        if v["code"] == "LUC_DEMAND":
            v["parameters"] = {}
    with pytest.raises(ValidationError, match="missing parameters"):
        Pack.model_validate(raw)


def _account(**facts: Any) -> dict:
    base = {
        "anchor_period": True,
        "obligation_status": "active",
        "pattern": "annual_demand",
        "subject_type": "property",
        "use_class": "commercial",
        "period_closed": True,
        "return_required": False,
        "return_due_at": None,
        "return_due_passed": False,
        "filed_count": 0,
        "filed_at": None,
        "filing_late_days": None,
        "transaction_count": 0,
        "demand_issued": True,
        "demand_served": True,
        "liability_established": True,
        "liability_amount": 120000.0,
        "payment_due_at": "2025-04-01T23:59:59+01:00",
        "payment_due_passed": True,
        "paid_total": 0.0,
        "settled_payment_count": 0,
        "first_payment_at": None,
        "payment_late_days": None,
        "residual_amount": 120000.0,
        "reversal_pending": False,
        "possible_unallocated_receipt": False,
        "legal_hold": False,
        "disputed": False,
    }
    base.update(facts)
    return {
        "kind": "account_period",
        "subject_type": "account",
        "subject_id": "DEMO-LUC-P001",
        "period": "2025",
        "tax_type": "LUC",
        "tax_head_name": "Land use charge",
        "facts": base,
        "quality": {
            "identity_verified": True,
            "match_confidence": 1.0,
            "staleness_days": 1,
            "coverage": {"filing": True, "payment": True},
        },
        "evidence": {},
        "history": {"filing": [], "payment": []},
    }


def test_head_rules_apply_to_any_head_and_name_it() -> None:
    o = evaluate(RULES["PAY-101"], _account())
    assert o.is_finding and o.consequence == 2 and o.priority is not None
    assert o.explanation and o.explanation.startswith("No settled Land use charge payment for 2025")
    # the same rule fires for a different head
    o = evaluate(RULES["PAY-101"], {**_account(), "tax_type": "MKT", "tax_head_name": "Market levies"})
    assert o.is_finding
    # head-agnostic rules never touch PAYE employer records
    assert evaluate(RULES["PAY-101"], {**_account(), "kind": "employer_period"}).outcome == "not_applicable"


def test_unserved_demand_is_a_billing_gap_not_a_taxpayer_default() -> None:
    rec = _account(demand_served=False, liability_established=False, payment_due_at=None)
    assert evaluate(RULES["PAY-101"], rec).outcome == "not_applicable"
    o = evaluate(RULES["DAT-102"], rec)
    assert o.is_finding and o.signal_class == "data_quality" and o.priority is None


def test_unknown_owner_is_a_data_hold() -> None:
    rec = _account()
    rec["quality"]["identity_verified"] = False
    o = evaluate(RULES["PAY-101"], rec)
    assert o.is_finding and o.data_hold and o.priority is None and "identity_unverified" in o.holds


def test_appeal_keeps_score_but_blocks_outward_action() -> None:
    o = evaluate(RULES["PAY-101"], _account(legal_hold=True))
    assert o.legal_hold and o.priority is not None and o.allowed_next_action == "internal_review_only"


def _profile(**facts: Any) -> dict:
    base = {
        "taxpayer_type": "individual",
        "taxpayer_status": "active",
        "income_indicator_count": 2,
        "income_indicator_heads": "BPR, LUC",
        "has_direct_assessment_account": False,
        "tax_year": "2025",
        "tax_year_due_passed": True,
        "direct_assessment_filed": False,
        "legal_hold": False,
        "disputed": False,
    }
    base.update(facts)
    return {
        "kind": "taxpayer_profile",
        "subject_type": "taxpayer",
        "subject_id": "DEMO-TP-I020",
        "period": "2025",
        "tax_type": "PITDA",
        "facts": base,
        "quality": {"identity_verified": True, "match_confidence": 1.0, "staleness_days": 1, "coverage": {}},
        "evidence": {},
    }


def test_cross_tax_rule() -> None:
    o = evaluate(RULES["REG-102"], _profile())
    assert o.is_finding and o.likelihood == 4
    assert "BPR, LUC" in (o.explanation or "")
    assert not evaluate(RULES["REG-102"], _profile(direct_assessment_filed=True)).is_finding
    assert evaluate(RULES["REG-102"], _profile(taxpayer_status="dormant")).outcome == "suppressed"
    assert evaluate(RULES["REG-102"], _profile(taxpayer_type="company")).outcome == "not_applicable"
    # unknown tax year (no approved legal version): never a score, only a data hold
    o = evaluate(RULES["REG-102"], _profile(tax_year=None, tax_year_due_passed=False))
    assert o.data_hold and "obligation_unverified" in o.holds and o.priority is None
