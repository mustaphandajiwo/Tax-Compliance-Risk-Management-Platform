"""Bundled NGSIRS pilot rule pack (12 deterministic PAYE-led rules)."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from ..dsl import RuleDefinition, validate_rule

PILOT_PACK = "ngsirs_pilot_v1.json"


def load_pilot_pack_raw() -> list[dict[str, Any]]:
    text = resources.files(__package__).joinpath(PILOT_PACK).read_text(encoding="utf-8")
    data: list[dict[str, Any]] = json.loads(text)
    return data


def load_pilot_pack() -> list[RuleDefinition]:
    return [validate_rule(r) for r in load_pilot_pack_raw()]
