"""Named predicates a rule may list as eligibility, exclusion or hold.

Predicates are tri-state: True, False or None (unknown). For eligibility, None
means "cannot establish" and becomes a hold rather than a pass or a fail: the
engine never treats unknown as compliant or as non-compliant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Tri = bool | None
Facts = dict[str, Any]


@dataclass(frozen=True)
class Predicate:
    name: str
    kinds: tuple[str, ...]
    fn: Callable[[Facts, dict[str, Any]], Tri]
    description: str


def _active_obligation(f: Facts, q: dict[str, Any]) -> Tri:
    status = f.get("obligation_status")
    if status == "active":
        return True
    if status == "pending_verification":
        return None
    return False


def _due_passed(due_field: str, passed_field: str) -> Callable[[Facts, dict[str, Any]], Tri]:
    def fn(f: Facts, q: dict[str, Any]) -> Tri:
        if f.get(due_field) is None:
            return None  # no approved legal due date: cannot establish
        return bool(f.get(passed_field))

    return fn


EP = ("employer_period",)

ELIGIBILITY: dict[str, Predicate] = {
    p.name: p
    for p in [
        Predicate(
            "active_obligation",
            EP,
            _active_obligation,
            "A legally approved PAYE obligation is active for the period",
        ),
        Predicate(
            "past_return_due_date",
            EP,
            _due_passed("return_due_at", "return_due_passed"),
            "The effective (extension-aware) return due date has passed",
        ),
        Predicate(
            "past_payment_due_date",
            EP,
            _due_passed("payment_due_at", "payment_due_passed"),
            "The effective remittance due date has passed",
        ),
        Predicate(
            "accepted_return_exists",
            EP,
            lambda f, q: (f.get("accepted_filing_count") or 0) > 0,
            "An accepted return exists for the period",
        ),
        Predicate(
            "served_assessment",
            ("assessment",),
            lambda f, q: bool(f.get("served")),
            "The assessment has been served",
        ),
        Predicate(
            "assessment_due_passed",
            ("assessment",),
            _due_passed("due_date", "due_passed"),
            "The assessment due date has passed",
        ),
    ]
}

EXCLUSIONS: dict[str, Predicate] = {
    p.name: p
    for p in [
        Predicate(
            "approved_extension",
            EP,
            lambda f, q: bool(f.get("extension_active")) and not f.get("return_due_passed"),
            "An approved extension moves the due date beyond the evaluation date",
        ),
        Predicate(
            "ceased_obligation",
            EP,
            lambda f, q: f.get("obligation_status") in ("ceased", "revoked"),
            "The obligation has ceased or been revoked",
        ),
        Predicate(
            "processing_delay",
            EP,
            lambda f, q: bool(f.get("processing_window_open")),
            "A submission is pending inside the processing window",
        ),
        Predicate(
            "source_conflict",
            EP,
            lambda f, q: bool(f.get("source_conflict")),
            "Sources disagree; routed to DAT-003 reconciliation",
        ),
        Predicate(
            "filing_coverage_incomplete",
            EP,
            lambda f, q: not (q.get("coverage") or {}).get("filing", False),
            "Accepted-filing coverage for the period is incomplete",
        ),
        Predicate(
            "payment_coverage_incomplete",
            EP,
            lambda f, q: not (q.get("coverage") or {}).get("payment", False),
            "Payment coverage for the period is incomplete or unreconciled",
        ),
        Predicate(
            "possible_unallocated_receipt",
            EP,
            lambda f, q: bool(f.get("possible_unallocated_receipt")),
            "A suspense/unallocated receipt may belong to this employer; routed to PAY-005",
        ),
        Predicate(
            "bank_delay_dispute",
            EP,
            lambda f, q: bool(f.get("bank_delay_dispute")),
            "An open bank-delay dispute covers the period",
        ),
        Predicate(
            "quarantined_period_records",
            EP,
            lambda f, q: bool(f.get("quarantined_period_records")),
            "Quarantined rows with invalid period IDs may belong to this period; routed to DAT-002",
        ),
        Predicate(
            "superseded_assessment",
            ("assessment",),
            lambda f, q: f.get("assessment_status") in ("superseded", "withdrawn"),
            "The assessment has been superseded or withdrawn",
        ),
    ]
}

HOLDS: dict[str, Predicate] = {
    p.name: p
    for p in [
        Predicate(
            "legal_hold",
            EP + ("assessment",),
            lambda f, q: bool(f.get("legal_hold")),
            "Appeal, stay or legal hold: enforcement workflow blocked",
        ),
        Predicate(
            "disputed",
            EP + ("assessment",),
            lambda f, q: bool(f.get("disputed")),
            "Taxpayer dispute recorded",
        ),
        Predicate(
            "reversal_unconfirmed",
            EP,
            lambda f, q: bool(f.get("reversal_pending")),
            "A payment reversal awaits treasury confirmation",
        ),
        Predicate(
            "extension_undecided",
            EP,
            lambda f, q: bool(f.get("extension_pending")),
            "An extension request is undecided",
        ),
    ]
}

# Hold reasons that make a finding a data-quality signal (no culpability score),
# versus legal holds that keep the score visible but block outward action.
DATA_HOLD_REASONS = {
    "identity_unverified",
    "stale_source",
    "obligation_unverified",
    "low_confidence",
    "reversal_unconfirmed",
    "extension_undecided",
}
LEGAL_HOLD_REASONS = {"legal_hold"}
DISPUTE_REASONS = {"disputed"}
