"""Reconciled rule catalogue.

The PRD (section 9) and the Technical Specification (section 23 pilot pack)
used the same codes for different rules. Rule codes are permanent
identifiers, so this catalogue adopts the Tech Spec pilot-pack meanings and
gives every PRD rule whose code would otherwise collide a new code. ``prd_code``
records where each entry came from. See docs/legal_config/rule_catalogue.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogueEntry:
    code: str
    domain: str
    title: str
    default_treatment: str
    status: str  # pilot | proposed_r1 | implemented_as_gate | retired_merged
    prd_code: str | None
    note: str = ""


CATALOGUE: list[CatalogueEntry] = [
    # --- Pilot pack (12, Tech Spec section 23) ---
    CatalogueEntry(
        "FIL-001",
        "filing",
        "PAYE accepted employer return missing for verified period",
        "review_then_approved_reminder",
        "pilot",
        "FIL-001",
    ),
    CatalogueEntry(
        "FIL-002",
        "filing",
        "PAYE return accepted after legally configured due date",
        "targeted_assistance",
        "pilot",
        None,
        "Repeat lateness raises likelihood (PRD FIL-002 intent)",
    ),
    CatalogueEntry(
        "FIL-003", "filing", "Repeated verified PAYE missing returns", "compliance_engagement", "pilot", None
    ),
    CatalogueEntry(
        "PAY-001",
        "payment",
        "PAYE remittance missing on settled due period",
        "payment_engagement",
        "pilot",
        "PAY-003",
        "Covers PRD PAY-003 (filed liability not reconciled to payment)",
    ),
    CatalogueEntry(
        "PAY-002", "payment", "PAYE remittance received after due date", "payment_engagement", "pilot", None
    ),
    CatalogueEntry(
        "PAY-003", "payment", "Repeated PAYE remittance lateness", "payment_engagement", "pilot", "PAY-002"
    ),
    CatalogueEntry(
        "PAY-004",
        "payment",
        "Remittance lower than verified declared payable amount",
        "payment_engagement",
        "pilot",
        "PAY-004",
    ),
    CatalogueEntry(
        "PAY-005",
        "data_quality",
        "Unallocated or unmatched PAYE receipt",
        "treasury_reconciliation",
        "pilot",
        "PAY-006",
    ),
    CatalogueEntry(
        "PAY-006",
        "payment",
        "Unresolved confirmed assessment balance",
        "debt_reconciliation",
        "pilot",
        "PAY-001",
    ),
    CatalogueEntry(
        "DAT-001",
        "data_quality",
        "Duplicate NGSIRS taxpayer identities",
        "identity_review",
        "pilot",
        "REG-002",
    ),
    CatalogueEntry(
        "DAT-002",
        "data_quality",
        "Missing or invalid period identifier",
        "internal_correction",
        "pilot",
        None,
    ),
    CatalogueEntry(
        "DAT-003",
        "data_quality",
        "Source payment/return conflict",
        "source_reconciliation",
        "pilot",
        "DAT-003",
    ),
    # --- Implemented as engine / import gates rather than rules ---
    CatalogueEntry(
        "DAT-004",
        "data_quality",
        "Unverified third-party or probabilistic match",
        "identity_review",
        "implemented_as_gate",
        "DAT-004",
        "Identity gate + data-steward match review queue",
    ),
    CatalogueEntry(
        "DAT-005",
        "data_quality",
        "Taxpayer identifier validation failure",
        "internal_correction",
        "implemented_as_gate",
        "DAT-001",
        "Import quarantine (invalid_identifier)",
    ),
    CatalogueEntry(
        "DAT-006",
        "data_quality",
        "Source extract stale",
        "source_reconciliation",
        "implemented_as_gate",
        "DAT-002",
        "Engine hard-stop: stale_source data hold",
    ),
    # --- Proposed for R1 (need data feeds not yet in the pilot) ---
    CatalogueEntry(
        "REG-001",
        "registration",
        "Employer in permitted licensing source but not in taxpayer register",
        "identity_review",
        "proposed_r1",
        "REG-001",
    ),
    CatalogueEntry(
        "REG-002",
        "registration",
        "Duplicate taxpayer identities (merged into DAT-001)",
        "identity_review",
        "retired_merged",
        "REG-002",
    ),
    CatalogueEntry(
        "REG-003",
        "registration",
        "Active licensed business with inactive tax account",
        "identity_review",
        "proposed_r1",
        "REG-003",
    ),
    CatalogueEntry(
        "REG-004",
        "registration",
        "Business location inconsistent with tax jurisdiction",
        "legal_review",
        "proposed_r1",
        "REG-004",
    ),
    CatalogueEntry(
        "REG-005",
        "registration",
        "Known employer with no PAYE obligation record",
        "legal_review",
        "proposed_r1",
        "REG-005",
    ),
    CatalogueEntry(
        "REG-006",
        "registration",
        "Branch or establishment unmatched to taxpayer parent",
        "identity_review",
        "proposed_r1",
        "REG-006",
    ),
    CatalogueEntry(
        "FIL-004",
        "filing",
        "Return rejected and not corrected",
        "targeted_assistance",
        "proposed_r1",
        "FIL-004",
    ),
    CatalogueEntry(
        "FIL-005",
        "filing",
        "Missing statutory employer annual filing",
        "review_then_approved_reminder",
        "proposed_r1",
        "FIL-005",
    ),
    CatalogueEntry(
        "FIL-006", "filing", "Inconsistent filing frequency", "desk_clarification", "proposed_r1", "FIL-006"
    ),
    CatalogueEntry(
        "FIL-007",
        "filing",
        "Repeated employer filing delays (>=3 of last 6)",
        "targeted_assistance",
        "proposed_r1",
        "FIL-002",
        "Renumbered: PRD FIL-002",
    ),
    CatalogueEntry(
        "FIL-008",
        "filing",
        "Filing interruption after sustained history (2 consecutive)",
        "legal_review",
        "proposed_r1",
        "FIL-003",
        "Renumbered: PRD FIL-003",
    ),
    CatalogueEntry(
        "REP-001",
        "reporting",
        "Material payroll decline unexplained",
        "desk_clarification",
        "proposed_r1",
        "REP-001",
    ),
    CatalogueEntry(
        "REP-002",
        "reporting",
        "Employee count varies materially",
        "desk_clarification",
        "proposed_r1",
        "REP-002",
    ),
    CatalogueEntry(
        "REP-003",
        "reporting",
        "Schedule total differs from return",
        "desk_clarification",
        "proposed_r1",
        "REP-003",
    ),
    CatalogueEntry(
        "REP-004",
        "reporting",
        "Employer declarations conflict with verified payroll",
        "desk_clarification",
        "proposed_r1",
        "REP-004",
    ),
    CatalogueEntry(
        "REP-005", "reporting", "Unusual amendment frequency", "desk_clarification", "proposed_r1", "REP-005"
    ),
    CatalogueEntry(
        "REP-006",
        "reporting",
        "Tax calculation inconsistent with approved rules",
        "desk_clarification",
        "proposed_r1",
        "REP-006",
    ),
    CatalogueEntry(
        "PAY-007",
        "payment",
        "Payment reversal not resolved",
        "treasury_reconciliation",
        "proposed_r1",
        "PAY-005",
        "Renumbered: PRD PAY-005; pilot handles via reversal holds",
    ),
    CatalogueEntry(
        "SYS-001", "systemic", "Sector-wide non-filing spike", "legal_review", "proposed_r1", "SYS-001"
    ),
    CatalogueEntry(
        "SYS-002",
        "systemic",
        "LGA concentration of registration discrepancies",
        "legal_review",
        "proposed_r1",
        "SYS-002",
    ),
    CatalogueEntry(
        "SYS-003",
        "systemic",
        "High filing failure after portal incident",
        "legal_review",
        "proposed_r1",
        "SYS-003",
    ),
    CatalogueEntry(
        "SYS-004",
        "systemic",
        "High error rate for a form or tax process",
        "legal_review",
        "proposed_r1",
        "SYS-004",
    ),
    CatalogueEntry(
        "SYS-005", "systemic", "Treatment campaign low response", "legal_review", "proposed_r1", "SYS-005"
    ),
    CatalogueEntry(
        "SYS-006",
        "systemic",
        "High audit false-positive rate for one rule",
        "legal_review",
        "proposed_r1",
        "SYS-006",
        "Surfaced on the rule dashboard as confirmed-findings rate",
    ),
]
