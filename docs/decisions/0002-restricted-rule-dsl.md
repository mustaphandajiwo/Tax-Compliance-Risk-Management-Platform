# 0002 Restricted declarative rule DSL

**Status:** accepted

## Context
Tech Spec section 7: rules are declarative JSON; arbitrary Python, SQL or executable code is prohibited;
every rule binds to an approved obligation and source-quality requirements.

## Decision
- Rules may only reference fields declared in `risk_engine/facts.py`, named predicates
  (`predicates.py`) and catalogued treatments (`treatment.py`). Operators are a fixed list; dates can
  only be tested for null (use derived boolean facts); nesting depth and node count are capped.
- `validate_rule` reports every problem at once and is enforced on draft, on activation and on every
  evaluation (`validate_rule(rv.expression_json)`).
- Taxpayer-facing rules must bind to an obligation and declare at least one exclusion. Data-quality rules
  cannot carry a consequence.
- Adding a *fact* is a reviewed code change; adding or changing a *rule* over existing facts is a
  configuration change governed by maker-checker.

## Consequences
Rule authors cannot express something the platform cannot explain. New risk concepts need a new fact,
which is deliberate friction.
