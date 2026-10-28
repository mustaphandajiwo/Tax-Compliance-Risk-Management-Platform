"""Restricted declarative rule language.

A rule is JSON. It can only reference declared facts (see ``facts.FACT_SCHEMA``),
named predicates (see ``predicates``), permitted operators and catalogued
treatments. There is no expression evaluation, no code, no SQL. ``validate_rule``
returns every problem it finds so a rule author sees the full list at once.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .facts import FACT_SCHEMA, HISTORY_FIELDS, HISTORY_SERIES
from .predicates import ELIGIBILITY, EXCLUSIONS, HOLDS
from .treatment import TREATMENTS

RULE_CODE_RE = re.compile(r"^(REG|FIL|REP|PAY|SYS|DAT)-\d{3}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
TEMPLATE_FIELD_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null"]
ORDERED_OPS = {"gt", "gte", "lt", "lte"}
NULL_OPS = {"is_null", "not_null"}
SET_OPS = {"in", "not_in"}
MAX_DEPTH = 4
MAX_NODES = 40

Domain = Literal["registration", "filing", "reporting", "payment", "systemic", "data_quality"]
SignalClass = Literal["taxpayer_risk", "data_quality", "debt_recovery"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(_Strict):
    tax_type: str
    entity: str
    fact_kind: str


class Quality(_Strict):
    max_staleness_days: int = Field(ge=0, le=365)
    min_match_confidence: float = Field(ge=0, le=1)
    require_coverage: list[Literal["filing", "payment", "assessment", "taxpayer"]] = []


class Adjustment(_Strict):
    when: list[dict[str, Any]]
    add: int = Field(ge=-2, le=2)


class Likelihood(_Strict):
    base: int = Field(ge=1, le=5)
    adjust: list[Adjustment] = []


class ConsequenceBands(_Strict):
    field: str
    # Ascending lower bounds; band n applies when value >= bounds[n-1].
    bounds: list[float] = Field(min_length=5, max_length=5)


class Signal(_Strict):
    likelihood: Likelihood
    consequence: Literal["unknown"] | ConsequenceBands = "unknown"
    effort: Literal["low", "medium", "high"] = "low"


class Approval(_Strict):
    author: str
    checker: str


class RuleDefinition(_Strict):
    id: str
    version: str
    domain: Domain
    title: str
    signal_class: SignalClass
    scope: Scope
    obligation_ref: str | None
    eligibility: list[str] = []
    input_refs: list[str]
    conditions: list[dict[str, Any]] = Field(min_length=1)
    exclusions: list[str] = []
    holds: list[str] = []
    quality: Quality
    signal: Signal
    treatment: str
    explanation: str
    alternative_explanations: list[str] = []
    references: list[str] = []
    approval: Approval

    @field_validator("id")
    @classmethod
    def _code(cls, v: str) -> str:
        if not RULE_CODE_RE.match(v):
            raise ValueError("rule id must look like FIL-001")
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError("version must be semantic (1.0.0)")
        return v


class RuleValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _check_value_type(
    ftype: str, spec: dict[str, Any], op: str, value: Any, where: str, errors: list[str]
) -> None:
    if op in NULL_OPS:
        if value is not None:
            errors.append(f"{where}: '{op}' takes no value")
        return
    values = value if op in SET_OPS else [value]
    if op in SET_OPS and (not isinstance(value, list) or not value):
        errors.append(f"{where}: '{op}' needs a non-empty list")
        return
    if op in ORDERED_OPS and ftype not in ("int", "number"):
        errors.append(f"{where}: '{op}' only applies to numeric fields")
        return
    if ftype in ("date", "datetime") and op not in NULL_OPS:
        errors.append(f"{where}: date fields only support is_null/not_null; use a derived boolean fact")
        return
    for v in values:
        ok = {
            "bool": isinstance(v, bool),
            "int": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "string": isinstance(v, str),
            "enum": isinstance(v, str) and v in spec.get("values", []),
        }.get(ftype, False)
        if not ok:
            errors.append(f"{where}: value {v!r} is not valid for {ftype} field")


def _validate_leaf(node: dict[str, Any], fields: dict[str, Any], where: str, errors: list[str]) -> None:
    allowed = {"field", "op", "value"}
    extra = set(node) - allowed
    if extra:
        errors.append(f"{where}: unknown keys {sorted(extra)}")
    field = node.get("field")
    op = node.get("op")
    if field not in fields:
        errors.append(f"{where}: unknown fact '{field}'")
        return
    if op not in Op.__args__:  # type: ignore[attr-defined]
        errors.append(f"{where}: operator '{op}' is not permitted")
        return
    spec = fields[field]
    ftype = spec["type"] if isinstance(spec, dict) else spec
    if op in ("is_null",) and isinstance(spec, dict) and not spec.get("nullable"):
        errors.append(f"{where}: '{field}' is never null")
    _check_value_type(ftype, spec if isinstance(spec, dict) else {}, op, node.get("value"), where, errors)


def _validate_node(
    node: Any, kind: str, depth: int, where: str, errors: list[str], counter: list[int]
) -> None:
    counter[0] += 1
    if counter[0] > MAX_NODES:
        if counter[0] == MAX_NODES + 1:
            errors.append(f"conditions exceed {MAX_NODES} nodes")
        return
    if depth > MAX_DEPTH:
        errors.append(f"{where}: nesting deeper than {MAX_DEPTH}")
        return
    if not isinstance(node, dict):
        errors.append(f"{where}: condition must be an object")
        return
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        if set(node) != {key} or not isinstance(node[key], list) or not node[key]:
            errors.append(f"{where}: '{key}' must be the only key and hold a non-empty list")
            return
        for i, child in enumerate(node[key]):
            _validate_node(child, kind, depth + 1, f"{where}.{key}[{i}]", errors, counter)
        return
    if "not" in node:
        if set(node) != {"not"}:
            errors.append(f"{where}: 'not' must be the only key")
            return
        _validate_node(node["not"], kind, depth + 1, f"{where}.not", errors, counter)
        return
    if "aggregate" in node:
        allowed = {"aggregate", "series", "window", "where", "op", "value"}
        extra = set(node) - allowed
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
        if node.get("aggregate") != "count":
            errors.append(f"{where}: only 'count' aggregate is permitted")
        if node.get("series") not in HISTORY_SERIES.get(kind, []):
            errors.append(f"{where}: unknown history series '{node.get('series')}' for {kind}")
        window = node.get("window")
        if not isinstance(window, int) or isinstance(window, bool) or not 1 <= window <= 36:
            errors.append(f"{where}: window must be an integer 1-36")
        if node.get("op") not in ORDERED_OPS | {"eq", "ne"}:
            errors.append(f"{where}: aggregate op must be a comparison")
        v = node.get("value")
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            errors.append(f"{where}: aggregate value must be a non-negative integer")
        where_nodes = node.get("where", [])
        if not isinstance(where_nodes, list):
            errors.append(f"{where}: 'where' must be a list")
            return
        hist_fields = {k: {"type": t} for k, t in HISTORY_FIELDS.items()}
        for i, leaf in enumerate(where_nodes):
            if not isinstance(leaf, dict) or "field" not in leaf:
                errors.append(f"{where}.where[{i}]: must be a field comparison")
                continue
            _validate_leaf(leaf, hist_fields, f"{where}.where[{i}]", errors)
        return
    _validate_leaf(node, FACT_SCHEMA.get(kind, {}), where, errors)


def validate_rule(raw: dict[str, Any]) -> RuleDefinition:
    """Parse and fully validate a rule. Raises RuleValidationError with all problems."""
    errors: list[str] = []
    try:
        rule = RuleDefinition.model_validate(raw)
    except ValidationError as exc:
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"])
            errors.append(f"{loc}: {e['msg']}")
        raise RuleValidationError(errors) from None

    kind = rule.scope.fact_kind
    if kind not in FACT_SCHEMA:
        errors.append(f"scope.fact_kind: unknown fact kind '{kind}'")
        raise RuleValidationError(errors)
    for name in rule.eligibility:
        if name not in ELIGIBILITY or kind not in ELIGIBILITY[name].kinds:
            errors.append(f"eligibility: '{name}' is not a permitted predicate for {kind}")
    for name in rule.exclusions:
        if name not in EXCLUSIONS or kind not in EXCLUSIONS[name].kinds:
            errors.append(f"exclusions: '{name}' is not a permitted exclusion for {kind}")
    for name in rule.holds:
        if name not in HOLDS or kind not in HOLDS[name].kinds:
            errors.append(f"holds: '{name}' is not a permitted hold for {kind}")
    counter = [0]
    for i, node in enumerate(rule.conditions):
        _validate_node(node, kind, 1, f"conditions[{i}]", errors, counter)
    for i, adj in enumerate(rule.signal.likelihood.adjust):
        for j, node in enumerate(adj.when):
            _validate_node(node, kind, 1, f"signal.likelihood.adjust[{i}].when[{j}]", errors, counter)
    cons = rule.signal.consequence
    if isinstance(cons, ConsequenceBands):
        spec = FACT_SCHEMA[kind].get(cons.field)
        if spec is None or spec["type"] not in ("int", "number"):
            errors.append(f"signal.consequence.field: '{cons.field}' must be a numeric fact")
        if list(cons.bounds) != sorted(cons.bounds):
            errors.append("signal.consequence.bounds must be ascending")
    if rule.treatment not in TREATMENTS:
        errors.append(f"treatment: '{rule.treatment}' is not in the treatment catalogue")
    for name in TEMPLATE_FIELD_RE.findall(rule.explanation):
        if name not in FACT_SCHEMA[kind] and name not in ("period", "subject_id"):
            errors.append(f"explanation: placeholder '{{{name}}}' is not a declared fact")
    if rule.signal_class != "data_quality" and not rule.exclusions and rule.domain != "data_quality":
        errors.append("exclusions: taxpayer-facing rules must declare at least one exclusion")
    if rule.signal_class != "data_quality" and rule.obligation_ref is None:
        errors.append("obligation_ref: taxpayer-facing rules must bind to a statutory obligation")
    if rule.signal_class == "data_quality" and rule.signal.consequence != "unknown":
        errors.append("signal.consequence: data-quality rules carry no consequence (taxpayer exposure)")
    if errors:
        raise RuleValidationError(errors)
    return rule
