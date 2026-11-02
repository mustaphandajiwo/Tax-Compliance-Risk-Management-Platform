"""Bundled rule packs: the PAYE pilot pack (12 rules) and the revenue-heads pack (10 rules that apply to
every configured head: personal income tax, withholding, capital gains, stamp duties, land use charge,
licences, levies)."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from ..dsl import RuleDefinition, validate_rule

PILOT_PACK = "paye_pilot_v1.json"
REVENUE_HEADS_PACK = "revenue_heads_v1.json"
PACKS = (PILOT_PACK, REVENUE_HEADS_PACK)


def load_pilot_pack_raw() -> list[dict[str, Any]]:
    """Every bundled rule, PAYE first."""
    data: list[dict[str, Any]] = []
    for name in PACKS:
        data.extend(json.loads(resources.files(__package__).joinpath(name).read_text(encoding="utf-8")))
    return data


def load_pilot_pack() -> list[RuleDefinition]:
    return [validate_rule(r) for r in load_pilot_pack_raw()]
