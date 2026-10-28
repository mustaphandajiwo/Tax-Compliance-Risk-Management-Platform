"""Deterministic rule evaluator.

``evaluate`` applies one validated rule to one fact record and returns an
``Outcome``. The order of checks is fixed and part of the contract:

1. scope         - wrong fact kind / tax type        -> not_applicable
2. exclusions    - a lawful reason the rule must not apply -> suppressed
3. eligibility   - False -> not_applicable; unknown -> hold (obligation_unverified)
4. conditions    - False -> not_triggered
5. hard-stop gates (identity, staleness, confidence, rule holds) -> hold flags
6. scoring       - L, C, priority; held data findings carry no culpability score

The same rule + the same fact record always gives the same outcome.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .dsl import ConsequenceBands, RuleDefinition
from .predicates import DATA_HOLD_REASONS, DISPUTE_REASONS, ELIGIBILITY, EXCLUSIONS, HOLDS, LEGAL_HOLD_REASONS
from .scoring import (
    clamp,
    consequence_from_bands,
    evidence_confidence,
    priority_band,
    priority_index,
)
from .treatment import TREATMENTS, allowed_next_action

TEMPLATE_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@dataclass
class Outcome:
    rule_code: str
    rule_version: str
    subject_type: str
    subject_id: str
    period: str | None
    outcome: str  # not_applicable | suppressed | not_triggered | triggered
    reasons: list[str] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    data_hold: bool = False
    legal_hold: bool = False
    disputed: bool = False
    signal_class: str | None = None
    likelihood: int | None = None
    consequence: int | None = None
    confidence: float | None = None
    priority: int | None = None
    priority_band: str | None = None
    priority_note: str | None = None
    treatment: str | None = None
    allowed_next_action: str | None = None
    explanation: str | None = None
    alternative_explanations: list[str] = field(default_factory=list)
    matched_conditions: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    evidence_values: dict[str, Any] = field(default_factory=dict)
    legal_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_finding(self) -> bool:
        return self.outcome == "triggered"


def _compare(actual: Any, op: str, value: Any) -> bool:
    if op == "is_null":
        return actual is None
    if op == "not_null":
        return actual is not None
    if op == "eq":
        return bool(actual == value)
    if op == "ne":
        return bool(actual != value)
    if op == "in":
        return actual in value
    if op == "not_in":
        return actual not in value
    if actual is None:
        return False  # unknown numeric never satisfies an ordered comparison
    if op == "gt":
        return bool(actual > value)
    if op == "gte":
        return bool(actual >= value)
    if op == "lt":
        return bool(actual < value)
    if op == "lte":
        return bool(actual <= value)
    raise ValueError(f"operator {op} not permitted")


def _eval_node(node: dict[str, Any], record: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    facts = record.get("facts", {})
    if "all" in node:
        return all(_eval_node(n, record, trace) for n in node["all"])
    if "any" in node:
        return any(_eval_node(n, record, trace) for n in node["any"])
    if "not" in node:
        return not _eval_node(node["not"], record, [])
    if "aggregate" in node:
        series = (record.get("history") or {}).get(node["series"], [])
        window = series[-node["window"] :]
        count = sum(
            1
            for entry in window
            if all(_compare(entry.get(w["field"]), w["op"], w.get("value")) for w in node.get("where", []))
        )
        result = _compare(count, node["op"], node["value"])
        if result:
            trace.append(
                {
                    "aggregate": "count",
                    "series": node["series"],
                    "window": node["window"],
                    "actual": count,
                    "op": node["op"],
                    "value": node["value"],
                    "periods": [
                        e.get("period")
                        for e in window
                        if all(
                            _compare(e.get(w["field"]), w["op"], w.get("value"))
                            for w in node.get("where", [])
                        )
                    ],
                }
            )
        return result
    actual = facts.get(node["field"])
    result = _compare(actual, node["op"], node.get("value"))
    if result:
        trace.append({"field": node["field"], "op": node["op"], "value": node.get("value"), "actual": actual})
    return result


def _render(template: str, record: dict[str, Any]) -> str:
    facts = record.get("facts", {})

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name == "period":
            return str(record.get("period") or "-")
        if name == "subject_id":
            return str(record.get("subject_id"))
        v = facts.get(name)
        if v is None:
            return "unknown"
        if isinstance(v, float):
            return f"{v:,.2f}"
        return str(v)

    return TEMPLATE_RE.sub(sub, template)


def _evidence(
    rule: RuleDefinition, record: dict[str, Any], trace: list[dict[str, Any]]
) -> tuple[list[str], dict]:
    ev = record.get("evidence") or {}
    refs: list[str] = []
    values: dict[str, Any] = {}
    fields = [t["field"] for t in trace if "field" in t]
    fields += [f"history.{t['series']}" for t in trace if "series" in t]
    cons = rule.signal.consequence
    if isinstance(cons, ConsequenceBands):
        fields.append(cons.field)
    for f in fields:
        for r in ev.get(f, []):
            if r not in refs:
                refs.append(r)
        if not f.startswith("history."):
            values[f] = record.get("facts", {}).get(f)
    for r in ev.get("_subject", []) + ev.get("_obligation", []):
        if r not in refs:
            refs.append(r)
    return refs, values


def _hold_treatment(holds: list[str]) -> str:
    if "identity_unverified" in holds:
        return "identity_review"
    if "obligation_unverified" in holds:
        return "legal_review"
    return "source_reconciliation"


def evaluate(rule: RuleDefinition, record: dict[str, Any], confidence_floor: float = 0.9) -> Outcome:
    out = Outcome(
        rule_code=rule.id,
        rule_version=rule.version,
        subject_type=record.get("subject_type", ""),
        subject_id=record.get("subject_id", ""),
        period=record.get("period"),
        outcome="not_applicable",
        legal_version=record.get("legal_version"),
    )
    if record.get("kind") != rule.scope.fact_kind or record.get("tax_type") != rule.scope.tax_type:
        out.reasons.append("out_of_scope")
        return out

    facts = record.get("facts", {})
    quality = record.get("quality", {})

    for name in rule.exclusions:
        if EXCLUSIONS[name].fn(facts, quality):
            out.outcome = "suppressed"
            out.reasons.append(name)
    if out.outcome == "suppressed":
        return out

    unknown_eligibility: list[str] = []
    for name in rule.eligibility:
        res = ELIGIBILITY[name].fn(facts, quality)
        if res is False:
            out.reasons.append(f"ineligible:{name}")
            return out
        if res is None:
            unknown_eligibility.append(name)

    trace: list[dict[str, Any]] = []
    if not all(_eval_node(n, record, trace) for n in rule.conditions):
        out.outcome = "not_triggered"
        return out

    out.outcome = "triggered"
    out.matched_conditions = trace
    out.signal_class = rule.signal_class
    out.treatment = rule.treatment
    out.alternative_explanations = list(rule.alternative_explanations)
    out.evidence_refs, out.evidence_values = _evidence(rule, record, trace)

    holds: list[str] = []
    out.confidence = evidence_confidence(
        quality, rule.quality.max_staleness_days, list(rule.quality.require_coverage)
    )
    # Data-quality rules are already review signals about records, not taxpayers,
    # so the taxpayer hard-stop gates do not apply to them.
    if rule.signal_class != "data_quality":
        if unknown_eligibility:
            holds.append("obligation_unverified")
        if not quality.get("identity_verified", False) or (
            float(quality.get("match_confidence", 0) or 0) < rule.quality.min_match_confidence
        ):
            holds.append("identity_unverified")
        staleness = quality.get("staleness_days")
        if staleness is None or staleness > rule.quality.max_staleness_days:
            holds.append("stale_source")
        for name in rule.holds:
            if HOLDS[name].fn(facts, quality):
                holds.append(name)
        if out.confidence < confidence_floor and not {"identity_unverified", "stale_source"} & set(holds):
            holds.append("low_confidence")
    out.holds = holds
    out.data_hold = any(h in DATA_HOLD_REASONS for h in holds)
    out.legal_hold = any(h in LEGAL_HOLD_REASONS for h in holds)
    out.disputed = any(h in DISPUTE_REASONS for h in holds)

    explanation = _render(rule.explanation, record)
    if out.data_hold:
        # Hard stop: a review / data-quality signal, never a culpability score.
        out.signal_class = "data_quality"
        out.treatment = _hold_treatment(holds)
        out.priority_note = "data_hold_no_score"
        out.explanation = f"REVIEW / DATA QUALITY ({', '.join(holds)}): {explanation}"
    else:
        lk = rule.signal.likelihood.base
        for adj in rule.signal.likelihood.adjust:
            if all(_eval_node(n, record, []) for n in adj.when):
                lk += adj.add
        out.likelihood = clamp(lk) if rule.signal_class != "data_quality" else None
        cons = rule.signal.consequence
        if isinstance(cons, ConsequenceBands):
            out.consequence = consequence_from_bands(facts.get(cons.field), cons.bounds)
        out.priority = priority_index(out.likelihood, out.consequence)
        out.priority_band = priority_band(out.priority)
        if rule.signal_class == "data_quality":
            out.priority_note = "data_quality_signal"
        elif out.priority is None:
            out.priority_note = "exposure_unknown"
        out.explanation = explanation
    out.allowed_next_action = allowed_next_action(
        out.signal_class or "", out.data_hold, out.legal_hold, out.disputed
    )
    assert out.treatment in TREATMENTS
    return out
