"""Risk scoring (Tech Spec section 9).

Likelihood L and consequence C are 1-5 rubric values. Queue priority is
4 x L x C (4-100) and exists only to order a review queue. Unknown consequence
stays None: it is never silently replaced by a high (or low) value. Evidence
confidence E is computed and shown separately; it gates workflow eligibility
and is never mixed into the priority number.
"""

from __future__ import annotations

from typing import Any

PRIORITY_BANDS = [(4, 20, "low"), (21, 45, "moderate"), (46, 70, "high"), (71, 100, "priority_review")]


def clamp(v: int, lo: int = 1, hi: int = 5) -> int:
    return max(lo, min(hi, v))


def consequence_from_bands(value: float | None, bounds: list[float]) -> int | None:
    if value is None or value <= 0:
        return None
    band = sum(1 for b in bounds if value >= b)
    return clamp(band) if band else None


def freshness_factor(staleness_days: int | None, sla_days: int) -> float:
    if staleness_days is None:
        return 0.0
    if sla_days <= 0:
        return 1.0 if staleness_days == 0 else 0.0
    half = sla_days / 2
    if staleness_days <= half:
        return 1.0
    if staleness_days > sla_days:
        return 0.0
    return round(1.0 - 0.5 * (staleness_days - half) / half, 4)


def evidence_confidence(
    quality: dict[str, Any], max_staleness_days: int, required_coverage: list[str]
) -> float:
    match = float(quality.get("match_confidence", 0.0) or 0.0)
    if not quality.get("identity_verified", False):
        match = min(match, 0.5)
    fresh = freshness_factor(quality.get("staleness_days"), max_staleness_days)
    coverage = quality.get("coverage") or {}
    cov = 1.0 if all(coverage.get(c, False) for c in required_coverage) else 0.5
    return round(match * fresh * cov, 4)


def priority_index(likelihood: int | None, consequence: int | None) -> int | None:
    if likelihood is None or consequence is None:
        return None
    return 4 * likelihood * consequence


def priority_band(priority: int | None) -> str | None:
    if priority is None:
        return None
    for lo, hi, name in PRIORITY_BANDS:
        if lo <= priority <= hi:
            return name
    return None
