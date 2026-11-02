"""Jurisdiction packs: everything that differs between revenue authorities, as configuration.

A pack (``jurisdictions/<name>/pack.json``) holds the authority's identity and branding, time zone,
currency, administrative areas and what they are called, taxpayer-ID format, data sources, legal
instruments and effective-dated obligation versions, tax scope, approved message templates, retention
periods, and the synthetic fixture used to demonstrate it. Onboarding another authority means writing a
pack, not changing code.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from importer import FEEDS

REPO = Path(__file__).resolve().parents[3]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Area(_Strict):
    code: str = Field(pattern=r"^[A-Z0-9]{2,8}$")
    name: str
    pilot: bool = False
    verified: bool = False


class Source(_Strict):
    name: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    feed_types: list[str]
    owner: str
    system_of_record: bool = True
    external: bool = False
    enabled: bool = True
    data_sharing_basis: str | None = None
    freshness_sla_days: int = Field(default=7, ge=1, le=365)

    @field_validator("feed_types")
    @classmethod
    def _feeds(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in FEEDS]
        if unknown:
            raise ValueError(f"unknown feed types {unknown}")
        return v


class Instrument(_Strict):
    code: str
    title: str
    authority: str
    jurisdiction: str
    status: str
    note: str


class LegalVersion(_Strict):
    code: str
    version: str
    instrument: str
    effective_from: date
    effective_to: date | None
    parameters: dict[str, Any]


class ScopeItem(_Strict):
    workstream: str
    status: Literal["pilot_primary", "secondary_next", "next", "future", "excluded"]
    treatment: str
    condition: str


class Retention(_Strict):
    data_class: str
    retain_days: int = Field(ge=1)
    legal_basis: str


class FixtureUser(_Strict):
    username: str
    display_name: str
    roles: str
    unit: str
    area_scope: str
    purposes: str


class Fixture(_Strict):
    places: list[str] = Field(min_length=10)
    users: list[FixtureUser]


class Pack(_Strict):
    code: str = Field(pattern=r"^[A-Z0-9-]{2,32}$")
    name: str
    short_name: str
    description: str
    fictional: bool
    country: str
    jurisdiction: str
    timezone: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    locale: str
    area_label: str
    area_label_plural: str
    tin_pattern: str
    settings: dict[str, Any]
    approved_templates: dict[str, str]
    areas: list[Area] = Field(min_length=1)
    data_sources: list[Source]
    data_sharing_basis: str
    instruments: list[Instrument]
    legal_versions: list[LegalVersion]
    tax_scope: list[ScopeItem]
    retention: list[Retention]
    fixture: Fixture

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        ZoneInfo(v)  # raises for an unknown zone
        return v

    @field_validator("tin_pattern")
    @classmethod
    def _re(cls, v: str) -> str:
        re.compile(v)
        return v

    @model_validator(mode="after")
    def _references(self) -> Pack:
        from .services.legal import OBLIGATION_CODES

        codes = {i.code for i in self.instruments}
        for v in self.legal_versions:
            if v.instrument not in codes:
                raise ValueError(
                    f"legal version {v.code} {v.version} cites unknown instrument {v.instrument}"
                )
            if v.code not in OBLIGATION_CODES:
                raise ValueError(f"unknown obligation code {v.code}")
            missing = [p for p in OBLIGATION_CODES[v.code]["required"] if p not in v.parameters]
            if missing:
                raise ValueError(f"{v.code} {v.version} is missing parameters {missing}")
        area_codes = [a.code for a in self.areas]
        if len(set(area_codes)) != len(area_codes):
            raise ValueError("area codes must be unique")
        return self

    def tenant_settings(self) -> dict[str, Any]:
        """What the running platform needs from the pack, stored on the tenant row."""
        return {
            **self.settings,
            "pack": self.code,
            "fictional": self.fictional,
            "timezone": self.timezone,
            "currency": self.currency,
            "locale": self.locale,
            "area_label": self.area_label,
            "area_label_plural": self.area_label_plural,
            "tin_pattern": self.tin_pattern,
            "approved_templates": self.approved_templates,
            "tax_scope": [s.model_dump() for s in self.tax_scope],
            "branding": {"authority_name": self.name, "short_name": self.short_name, "logo": None},
        }


def packs_dir() -> Path:
    from .config import get_settings

    configured = get_settings().jurisdictions_path
    return Path(configured) if configured else REPO / "jurisdictions"


@lru_cache
def load_pack(name: str) -> Pack:
    path = packs_dir() / name / "pack.json"
    if not path.exists():
        raise FileNotFoundError(f"No jurisdiction pack '{name}' at {path}")
    return Pack.model_validate(json.loads(path.read_text()))


def available_packs() -> list[str]:
    return sorted(p.parent.name for p in packs_dir().glob("*/pack.json"))
