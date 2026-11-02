"""Canonical feed profiles.

A profile lists canonical columns, their types and which columns form the
natural key used for de-duplication and supersession. Source files may use
other column names; a field mapping translates them without losing the
original values (the raw row is kept in provenance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ColType = Literal[
    "str", "int", "decimal", "date", "datetime", "period", "tax_period", "bool", "enum", "identifier"
]


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
    account_ref_column: str | None = None

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def required(self) -> list[str]:
        return [c.name for c in self.columns if c.required]


FEEDS: dict[str, FeedProfile] = {
    p.feed_type: p
    for p in [
        FeedProfile(
            "taxpayer",
            "Taxpayer register",
            "Registered taxpayers held by the authority",
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
                Column("area_code", "str", required=False),
                Column("sector", "str", required=False),
                Column("effective_from", "date", required=False),
                Column("effective_to", "date", required=False),
            ),
            ("source_taxpayer_id",),
            safeguard="Duplicate review and pseudonymisation",
        ),
        FeedProfile(
            "employer",
            "Employer register",
            "PAYE employers and their link to taxpayer records",
            (
                Column("source_employer_id", "str"),
                Column("linked_taxpayer_id", "str", required=False),
                Column("employer_name", "str"),
                Column("activity_from", "date", required=False),
                Column("activity_to", "date", required=False),
                Column("office_id", "str", required=False),
                Column("area_code", "str", required=False),
                Column("sector", "str", required=False),
                Column("segment", "enum", required=False, values=("large", "medium", "small", "micro")),
                Column("status", "enum", values=("active", "inactive", "ceased")),
            ),
            ("source_employer_id",),
            employer_ref_column="source_employer_id",
            safeguard="Link confidence and business activity evidence",
        ),
        FeedProfile(
            "obligation",
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
            "extension",
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
            "paye_return",
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
            "payment",
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
            "assessment",
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
        FeedProfile(
            "revenue_account",
            "Revenue head accounts",
            "Accounts under each configured revenue head: individuals, agents, operators, properties, "
            "business premises and vehicles, linked to the taxpayer register",
            (
                Column("account_id", "str"),
                Column("tax_head", "str", description="Revenue head code from the jurisdiction pack"),
                Column(
                    "subject_type",
                    "enum",
                    values=("individual", "agent", "operator", "property", "premises", "vehicle", "business"),
                ),
                Column("taxpayer_id", "str", required=False, description="Linked taxpayer register ID"),
                Column("employer_id", "str", required=False),
                Column("account_name", "str"),
                Column("area_code", "str", required=False),
                Column(
                    "use_class",
                    "enum",
                    required=False,
                    values=("residential", "commercial", "mixed", "industrial", "institutional", "private"),
                ),
                Column("category", "str", required=False, description="Vehicle class, premises category ..."),
                Column("assessed_value", "decimal", required=False),
                Column("status", "enum", values=("active", "ceased", "exempt", "pending_verification")),
                Column("effective_from", "date"),
                Column("effective_to", "date", required=False),
            ),
            ("account_id",),
            safeguard="Only accounts under a configured head; owner identity verified before any taxpayer signal",
            account_ref_column="account_id",
        ),
        FeedProfile(
            "revenue_liability",
            "Revenue head returns, demands, renewals and transactions",
            "Returns filed, demand notices served, licence expiries and registry transactions per account",
            (
                Column("liability_reference", "str"),
                Column("account_id", "str"),
                Column("tax_head", "str"),
                Column("period", "tax_period", description="YYYY-MM, or YYYY for annual heads"),
                Column("kind", "enum", values=("return", "demand", "renewal_due", "transaction", "levy")),
                Column(
                    "status",
                    "enum",
                    values=("filed", "accepted", "rejected", "served", "issued", "recorded", "withdrawn"),
                ),
                Column(
                    "event_date", "date", required=False, description="Service, expiry or transaction date"
                ),
                Column("filed_at", "datetime", required=False),
                Column("amount", "decimal", required=False),
                Column(
                    "appeal_status", "enum", required=False, values=("none", "appealed", "stayed", "resolved")
                ),
            ),
            ("liability_reference",),
            safeguard="A demand counts only once served; a transaction only from a system-of-record registry",
            period_columns=("period",),
            account_ref_column="account_id",
        ),
        FeedProfile(
            "revenue_payment",
            "Revenue head payments",
            "Collections for every revenue head from treasury or the collection platform",
            (
                Column("payment_reference", "str"),
                Column("account_id", "str", required=False),
                Column("tax_head", "str"),
                Column("period", "tax_period", required=False),
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
            ),
            ("payment_reference",),
            safeguard="Reconciliation and reversal handling",
            period_columns=("period",),
            account_ref_column="account_id",
        ),
    ]
}

SCHEMA_VERSION = "taxrisk-feeds/1.1"
