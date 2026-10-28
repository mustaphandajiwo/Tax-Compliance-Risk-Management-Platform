"""NGSIRS canonical feed profiles (Tech Spec section 23).

A profile lists canonical columns, their types and which columns form the
natural key used for de-duplication and supersession. Source files may use
other column names; a field mapping translates them without losing the
original values (the raw row is kept in provenance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ColType = Literal["str", "int", "decimal", "date", "datetime", "period", "bool", "enum", "identifier"]


@dataclass(frozen=True)
class Column:
    name: str
    type: ColType
    required: bool = True
    values: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class FeedProfile:
    feed_type: str
    title: str
    description: str
    columns: tuple[Column, ...]
    natural_key: tuple[str, ...]
    employer_ref_column: str | None = None
    safeguard: str = ""
    period_columns: tuple[str, ...] = field(default=())

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def required(self) -> list[str]:
        return [c.name for c in self.columns if c.required]


FEEDS: dict[str, FeedProfile] = {
    p.feed_type: p
    for p in [
        FeedProfile(
            "ngsirs_taxpayer",
            "Taxpayer register",
            "Registered taxpayers held by NGSIRS",
            (
                Column("source_taxpayer_id", "str"),
                Column(
                    "taxpayer_type",
                    "enum",
                    values=("company", "individual", "partnership", "government", "ngo"),
                ),
                Column("status", "enum", values=("active", "inactive", "dormant", "deregistered")),
                Column("taxpayer_name", "str", description="Synthetic name in demo; tokenised on ingest"),
                Column("tin", "identifier", description="Tax identification number; encrypted at rest"),
                Column("jurisdiction", "str"),
                Column("lga_code", "str", required=False),
                Column("sector", "str", required=False),
                Column("effective_from", "date", required=False),
                Column("effective_to", "date", required=False),
            ),
            ("source_taxpayer_id",),
            safeguard="Duplicate review and pseudonymisation",
        ),
        FeedProfile(
            "ngsirs_employer",
            "Employer register",
            "PAYE employers and their link to taxpayer records",
            (
                Column("source_employer_id", "str"),
                Column("linked_taxpayer_id", "str", required=False),
                Column("employer_name", "str"),
                Column("activity_from", "date", required=False),
                Column("activity_to", "date", required=False),
                Column("office_id", "str", required=False),
                Column("lga_code", "str", required=False),
                Column("sector", "str", required=False),
                Column("segment", "enum", required=False, values=("large", "medium", "small", "micro")),
                Column("status", "enum", values=("active", "inactive", "ceased")),
            ),
            ("source_employer_id",),
            employer_ref_column="source_employer_id",
            safeguard="Link confidence and business activity evidence",
        ),
        FeedProfile(
            "ngsirs_obligation",
            "Obligation register",
            "Legal-team-approved tax obligations per employer",
            (
                Column("taxpayer_id", "str", description="Employer reference the obligation applies to"),
                Column("tax_type", "enum", values=("PAYE",)),
                Column("obligation_type", "enum", values=("paye_employer",)),
                Column("legal_code", "str", required=False),
                Column("statutory_version", "str", required=False),
                Column("effective_from", "date"),
                Column("effective_to", "date", required=False),
                Column("status", "enum", values=("active", "ceased", "revoked", "pending_verification")),
                Column("exemption_status", "enum", required=False, values=("none", "exempt", "partial")),
            ),
            ("taxpayer_id", "tax_type", "obligation_type", "effective_from"),
            employer_ref_column="taxpayer_id",
            safeguard="Only legal-team-approved obligations are eligible",
        ),
        FeedProfile(
            "ngsirs_extension",
            "Extensions",
            "Approved or pending due-date extensions",
            (
                Column("employer_id", "str"),
                Column("obligation_type", "enum", values=("paye_return", "paye_remittance")),
                Column("period", "period"),
                Column("new_due_date", "date"),
                Column("status", "enum", values=("approved", "pending", "refused")),
                Column("approved_by", "str", required=False),
            ),
            ("employer_id", "obligation_type", "period"),
            employer_ref_column="employer_id",
            period_columns=("period",),
        ),
        FeedProfile(
            "ngsirs_paye_return",
            "PAYE employer returns",
            "Monthly PAYE returns from filing systems",
            (
                Column("filing_reference", "str"),
                Column("employer_id", "str"),
                Column("period", "period"),
                Column(
                    "status",
                    "enum",
                    values=("draft", "submitted", "accepted", "rejected", "corrected", "not_received"),
                ),
                Column("submitted_at", "datetime", required=False),
                Column("accepted_at", "datetime", required=False),
                Column("amount_declared", "decimal", required=False),
                Column("employee_count", "int", required=False),
            ),
            ("filing_reference",),
            employer_ref_column="employer_id",
            safeguard="Distinguish drafts, corrections and accepted returns",
            period_columns=("period",),
        ),
        FeedProfile(
            "ngsirs_payment",
            "PAYE payments",
            "Remittances from bank / treasury collection systems",
            (
                Column("payment_reference", "str"),
                Column("employer_id", "str", required=False),
                Column("tax_type", "enum", values=("PAYE",)),
                Column("period", "period", required=False),
                Column("paid_at", "datetime"),
                Column("amount", "decimal"),
                Column("reversal_status", "enum", values=("none", "reversed", "reversal_pending")),
                Column("settlement_status", "enum", required=False, values=("settled", "pending")),
                Column(
                    "allocation_status",
                    "enum",
                    required=False,
                    values=("allocated", "unallocated", "suspense"),
                ),
                Column("bank_delay_dispute", "bool", required=False),
                Column("credit_adjustment", "decimal", required=False),
            ),
            ("payment_reference",),
            employer_ref_column="employer_id",
            safeguard="Reconciliation and reversal handling",
            period_columns=("period",),
        ),
        FeedProfile(
            "ngsirs_assessment",
            "Assessments",
            "Served PAYE assessments and balances",
            (
                Column("assessment_id", "str"),
                Column("employer_id", "str"),
                Column("period", "period"),
                Column(
                    "assessment_type", "enum", values=("best_of_judgement", "additional", "self_declared")
                ),
                Column("amount", "decimal"),
                Column("served_on", "date", required=False),
                Column("due_date", "date", required=False),
                Column("appeal_status", "enum", values=("none", "appealed", "stayed", "resolved")),
                Column("outstanding_amount", "decimal"),
                Column("status", "enum", values=("served", "superseded", "withdrawn", "draft")),
            ),
            ("assessment_id",),
            employer_ref_column="employer_id",
            safeguard="Never infer overdue balance from unmatched payments alone",
            period_columns=("period",),
        ),
    ]
}

SCHEMA_VERSION = "ngsirs-feeds/1.0"
