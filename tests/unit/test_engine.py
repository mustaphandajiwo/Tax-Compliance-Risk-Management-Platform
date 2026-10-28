"""Risk engine: DSL validation, evaluation order, hard stops and scoring."""

from __future__ import annotations

import copy

import pytest

from risk_engine import RuleValidationError, evaluate, load_pilot_pack, validate_rule
from risk_engine.evaluator import Outcome
from risk_engine.hashing import sha256_hex
from risk_engine.rulepack import load_pilot_pack_raw
from risk_engine.scoring import consequence_from_bands, freshness_factor, priority_band, priority_index
from tests.unit.helpers import assessment, employer_period

RULES = {r.id: r for r in load_pilot_pack()}
RAW = {r["id"]: r for r in load_pilot_pack_raw()}


def run(code: str, record: dict) -> Outcome:
    return evaluate(RULES[code], record)


# --- DSL -----------------------------------------------------------------------------------


def test_pilot_pack_has_twelve_valid_rules() -> None:
    assert sorted(RULES) == sorted(
        [
            "FIL-001",
            "FIL-002",
            "FIL-003",
            "PAY-001",
            "PAY-002",
            "PAY-003",
            "PAY-004",
            "PAY-005",
            "PAY-006",
            "DAT-001",
            "DAT-002",
            "DAT-003",
        ]
    )


def _mutated(code: str, **changes: object) -> dict:
    rule = copy.deepcopy(RAW[code])
    rule.update(changes)
    return rule


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"conditions": [{"field": "does_not_exist", "op": "eq", "value": 1}]}, "unknown fact"),
        ({"conditions": [{"field": "accepted_filing_count", "op": "regex", "value": ".*"}]}, "not permitted"),
        ({"conditions": [{"field": "obligation_status", "op": "gt", "value": "active"}]}, "numeric"),
        ({"conditions": [{"field": "return_due_at", "op": "eq", "value": "2026-01-01"}]}, "date fields"),
        ({"conditions": [{"field": "obligation_status", "op": "eq", "value": "bogus"}]}, "not valid"),
        (
            {"conditions": [{"field": "accepted_filing_count", "op": "eq", "value": "__import__('os')"}]},
            "not valid",
        ),
        ({"exclusions": []}, "at least one exclusion"),
        ({"exclusions": ["drop_table"]}, "not a permitted exclusion"),
        ({"eligibility": ["served_assessment"]}, "not a permitted predicate"),
        ({"treatment": "seize_bank_account"}, "treatment catalogue"),
        ({"obligation_ref": None}, "statutory obligation"),
        ({"explanation": "Missing {secret_field}"}, "placeholder"),
        ({"python": "print(1)"}, "Extra inputs"),
        ({"id": "FIL-1"}, "rule id"),
        ({"version": "1.0"}, "semantic"),
    ],
)
def test_validator_rejects_unsafe_or_invalid_rules(changes: dict, message: str) -> None:
    with pytest.raises(RuleValidationError) as exc:
        validate_rule(_mutated("FIL-001", **changes))
    assert any(message in e for e in exc.value.errors), exc.value.errors


def test_validator_limits_nesting_depth() -> None:
    node: dict = {"field": "accepted_filing_count", "op": "eq", "value": 0}
    for _ in range(6):
        node = {"all": [node]}
    with pytest.raises(RuleValidationError) as exc:
        validate_rule(_mutated("FIL-001", conditions=[node]))
    assert any("nesting" in e for e in exc.value.errors)


def test_data_quality_rules_cannot_carry_consequence() -> None:
    raw = copy.deepcopy(RAW["PAY-005"])
    raw["signal"]["consequence"] = {"field": "amount", "bounds": [1, 2, 3, 4, 5]}
    with pytest.raises(RuleValidationError):
        validate_rule(raw)


# --- evaluation order and outcomes ----------------------------------------------------------------


def test_fil001_triggers_for_verified_missing_return_with_unknown_exposure() -> None:
    o = run("FIL-001", employer_period())
    assert o.outcome == "triggered"
    assert o.likelihood == 3 and o.consequence is None and o.priority is None
    assert o.priority_note == "exposure_unknown"
    assert o.allowed_next_action == "internal_review"
    assert "2026-06" in (o.explanation or "")
    assert "src:employer:NGS-DEMO-EMP-0001" in o.evidence_refs


def test_fil001_suppressed_by_approved_extension() -> None:
    o = run("FIL-001", employer_period(extension_active=True, return_due_passed=False))
    assert o.outcome == "suppressed" and "approved_extension" in o.reasons


def test_fil001_does_not_fire_when_return_accepted() -> None:
    assert run("FIL-001", employer_period(accepted_filing_count=1)).outcome == "not_triggered"


def test_fil001_suppressed_when_filing_coverage_incomplete() -> None:
    o = run("FIL-001", employer_period(coverage={"filing": False, "payment": True}))
    assert o.outcome == "suppressed" and "filing_coverage_incomplete" in o.reasons


def test_no_obligation_is_not_applicable_not_noncompliant() -> None:
    o = run("FIL-001", employer_period(obligation_status="none"))
    assert o.outcome == "not_applicable" and not o.is_finding


@pytest.mark.parametrize(
    ("overrides", "hold"),
    [
        ({"identity_verified": False, "match_confidence": 0.7}, "identity_unverified"),
        ({"match_confidence": 0.95}, "identity_unverified"),
        ({"staleness_days": 30}, "stale_source"),
        ({"staleness_days": None}, "stale_source"),
        ({"obligation_status": "pending_verification"}, "obligation_unverified"),
        ({"extension_pending": True}, "extension_undecided"),
    ],
)
def test_hard_stops_produce_data_quality_signal_without_score(overrides: dict, hold: str) -> None:
    o = run("FIL-001", employer_period(**overrides))
    assert o.outcome == "triggered"
    assert hold in o.holds
    assert o.data_hold and o.signal_class == "data_quality"
    assert o.likelihood is None and o.consequence is None and o.priority is None
    assert o.priority_note == "data_hold_no_score"
    assert o.allowed_next_action == "data_review"


def test_unknown_due_date_is_a_hold_not_a_pass() -> None:
    o = run("FIL-001", employer_period(return_due_at=None, return_due_passed=False))
    assert o.outcome == "triggered" and "obligation_unverified" in o.holds


def test_legal_hold_keeps_score_but_blocks_outward_action() -> None:
    o = run("PAY-006", assessment(appeal_status="appealed", legal_hold=True))
    assert o.outcome == "triggered" and o.legal_hold and not o.data_hold
    assert o.priority is not None
    assert o.allowed_next_action == "internal_review_only"


def test_superseded_assessment_suppressed() -> None:
    assert run("PAY-006", assessment(assessment_status="superseded")).outcome == "suppressed"


def test_pay001_suppressed_by_unallocated_receipt() -> None:
    o = run("PAY-001", employer_period(possible_unallocated_receipt=True))
    assert o.outcome == "suppressed" and "possible_unallocated_receipt" in o.reasons


def test_pay001_consequence_from_declared_payable() -> None:
    o = run("PAY-001", employer_period(declared_payable=750000.0, accepted_filing_count=1))
    assert o.consequence == 3 and o.priority == 4 * 3 * 3 and o.priority_band == "moderate"


def test_pay004_respects_tolerance() -> None:
    within = employer_period(
        accepted_filing_count=1, declared_payable=100000.0, settled_payment_count=1, residual_amount=500.0
    )
    assert run("PAY-004", within).outcome == "not_triggered"
    above = employer_period(
        accepted_filing_count=1, declared_payable=100000.0, settled_payment_count=1, residual_amount=40000.0
    )
    assert run("PAY-004", above).outcome == "triggered"


def _history(missing: list[bool]) -> dict:
    entries = [
        {"period": f"2026-{i + 1:02d}", "eligible": True, "missing": m, "late": False}
        for i, m in enumerate(missing)
    ]
    return {"filing": entries, "payment": []}


def test_fil003_counts_only_last_six_periods() -> None:
    old_misses = _history([True, True, True, False, False, False, False, False, False])
    assert run("FIL-003", employer_period(anchor_period=True, history=old_misses)).outcome == "not_triggered"
    recent = _history([False, False, False, True, False, True, False, True, True])
    assert run("FIL-003", employer_period(anchor_period=True, history=recent)).outcome == "triggered"
    assert run("FIL-003", employer_period(anchor_period=False, history=recent)).outcome == "not_triggered"


def test_repeat_misses_raise_fil001_likelihood() -> None:
    o = run("FIL-001", employer_period(history=_history([True, True, True])))
    assert o.likelihood == 4


def test_data_quality_rules_are_not_taxpayer_scores() -> None:
    rec = {
        "kind": "payment_receipt",
        "subject_type": "payment",
        "subject_id": "P1",
        "period": None,
        "tax_type": "PAYE",
        "facts": {"allocation_status": "suspense", "employer_matched": True, "amount": 10.0, "age_days": 3},
        "quality": {"identity_verified": False, "match_confidence": 0, "staleness_days": 1, "coverage": {}},
        "evidence": {},
    }
    o = run("PAY-005", rec)
    assert o.outcome == "triggered" and not o.data_hold
    assert o.likelihood is None and o.priority is None and o.priority_note == "data_quality_signal"
    assert "not evidence of taxpayer non-payment" in (o.explanation or "")


def test_evaluation_is_deterministic() -> None:
    rec = employer_period(declared_payable=750000.0, accepted_filing_count=0)
    hashes = {sha256_hex(run("PAY-001", copy.deepcopy(rec)).to_dict()) for _ in range(5)}
    assert len(hashes) == 1


def test_scope_mismatch_is_not_applicable() -> None:
    assert run("PAY-006", employer_period()).outcome == "not_applicable"


# --- scoring -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "band"),
    [
        (4, "low"),
        (20, "low"),
        (21, "moderate"),
        (45, "moderate"),
        (46, "high"),
        (70, "high"),
        (71, "priority_review"),
        (100, "priority_review"),
        (None, None),
    ],
)
def test_priority_bands(p: int | None, band: str | None) -> None:
    assert priority_band(p) == band


def test_priority_index_range_and_unknown() -> None:
    assert priority_index(1, 1) == 4 and priority_index(5, 5) == 100
    assert priority_index(3, None) is None


def test_consequence_bands() -> None:
    bounds = [1, 100000, 500000, 2000000, 10000000]
    assert consequence_from_bands(None, bounds) is None
    assert consequence_from_bands(0, bounds) is None
    assert consequence_from_bands(50, bounds) == 1
    assert consequence_from_bands(100000, bounds) == 2
    assert consequence_from_bands(99_000_000, bounds) == 5


def test_freshness_factor() -> None:
    assert freshness_factor(0, 7) == 1.0
    assert freshness_factor(7, 7) == 0.5
    assert freshness_factor(8, 7) == 0.0
    assert freshness_factor(None, 7) == 0.0
