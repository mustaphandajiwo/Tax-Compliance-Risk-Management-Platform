"""Fact schema: the only inputs a rule may reference.

Rules never touch the database. A facts builder (in the API service) turns
quality-checked canonical records into *fact records*, one per subject (and
period where relevant). Each fact record is plain JSON so it can be frozen into
an immutable input snapshot and re-evaluated later to reproduce a score.

Every field a rule references must be declared here with a type. The DSL
validator rejects any rule that references an undeclared field, which is what
keeps the rule language closed: rules can combine facts, never compute new ones.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

FieldType = Literal["bool", "int", "number", "string", "date", "datetime", "enum"]


class FieldSpec(TypedDict, total=False):
    type: FieldType
    nullable: bool
    values: list[str]
    description: str


HistoryEntry = dict[str, Any]
"""One period of a history series: {"period", "eligible", "missing", "late"}."""

FactRecord = dict[str, Any]
"""A JSON fact record: kind, subject_type, subject_id, period, tax_type, facts, history, quality, evidence,
legal_versions, area_code and (optionally) employer_ref. Plain JSON so it can be frozen into a snapshot."""


def _f(t: FieldType, desc: str, nullable: bool = False, values: list[str] | None = None) -> FieldSpec:
    spec: FieldSpec = {"type": t, "nullable": nullable, "description": desc}
    if values is not None:
        spec["values"] = values
    return spec


OBLIGATION_STATUSES = ["active", "ceased", "revoked", "none", "pending_verification"]

# Fact kinds and their fields. Kept intentionally explicit: adding a field is a
# code change reviewed like any other, adding a rule over existing fields is not.
FACT_SCHEMA: dict[str, dict[str, FieldSpec]] = {
    "employer_period": {
        "anchor_period": _f("bool", "Latest due period in the evaluation window (for repeat-pattern rules)"),
        "obligation_status": _f("enum", "PAYE obligation status for the period", values=OBLIGATION_STATUSES),
        "return_due_at": _f("datetime", "Effective return due date (extension-aware)", nullable=True),
        "payment_due_at": _f("datetime", "Effective remittance due date (extension-aware)", nullable=True),
        "return_due_passed": _f("bool", "Effective return due date has passed at evaluation time"),
        "payment_due_passed": _f("bool", "Effective remittance due date has passed at evaluation time"),
        "extension_active": _f("bool", "An approved extension applies to this period"),
        "extension_pending": _f("bool", "Extension requested but not yet decided"),
        "accepted_filing_count": _f("int", "Accepted returns for the period (by event time)"),
        "accepted_at": _f("datetime", "Earliest acceptance timestamp", nullable=True),
        "filing_late_days": _f("int", "Days accepted after effective due date", nullable=True),
        "submission_pending": _f("bool", "Submitted but not yet accepted or rejected"),
        "processing_window_open": _f("bool", "A pending submission is still inside the processing window"),
        "rejected_uncorrected": _f("bool", "Latest submission rejected and not corrected"),
        "declared_payable": _f(
            "number", "Payable declared on the accepted return (authority currency)", nullable=True
        ),
        "paid_allocated_total": _f("number", "Settled, non-reversed remittance allocated to the period"),
        "credits_adjustments_total": _f("number", "Approved credits/adjustments for the period"),
        "residual_amount": _f(
            "number", "declared_payable - paid - credits (authority currency)", nullable=True
        ),
        "settled_payment_count": _f("int", "Settled, non-reversed payments allocated to the period"),
        "first_payment_at": _f("datetime", "Earliest settled remittance timestamp", nullable=True),
        "payment_late_days": _f("int", "Days earliest remittance posted after due date", nullable=True),
        "reversed_payment_count": _f("int", "Payments for the period that were reversed"),
        "reversal_pending": _f("bool", "A reversal is awaiting treasury confirmation"),
        "possible_unallocated_receipt": _f("bool", "Employer has suspense/unallocated receipts in window"),
        "bank_delay_dispute": _f("bool", "Employer has an open bank-delay dispute for the period"),
        "quarantined_period_records": _f("bool", "Employer has quarantined rows with invalid period IDs"),
        "source_conflict": _f("bool", "Sources disagree about this period's filing or payment"),
        "legal_hold": _f("bool", "Appeal, stay or other legal hold applies"),
        "disputed": _f("bool", "Taxpayer has disputed a finding for this period"),
    },
    "assessment": {
        "assessment_status": _f(
            "enum", "Assessment status", values=["served", "superseded", "withdrawn", "draft"]
        ),
        "served": _f("bool", "Assessment has been lawfully served"),
        "due_date": _f("date", "Assessment payment due date", nullable=True),
        "due_passed": _f("bool", "Assessment due date has passed"),
        "appeal_status": _f("enum", "Appeal status", values=["none", "appealed", "stayed", "resolved"]),
        "outstanding_amount": _f("number", "Net valid outstanding amount (authority currency)"),
        "assessed_amount": _f("number", "Assessed amount (authority currency)"),
        "employer_ref": _f("string", "Employer the assessment was raised against"),
        "legal_hold": _f("bool", "Appeal or stay in force"),
        "disputed": _f("bool", "Taxpayer dispute recorded"),
    },
    "taxpayer_pair": {
        "shared_identifier_count": _f("int", "Identifier tokens shared by the two records"),
        "name_similarity": _f("number", "Normalised name-token similarity 0-1"),
        "same_area": _f("bool", "Both records are in the same administrative area"),
    },
    "quarantined_record": {
        "feed_type": _f("string", "Feed the record came from"),
        "reason_code": _f("string", "Quarantine reason code"),
        "employer_known": _f("bool", "Row names a known employer"),
    },
    "payment_receipt": {
        "allocation_status": _f("enum", "Allocation status", values=["allocated", "unallocated", "suspense"]),
        "employer_matched": _f("bool", "Payment reference resolves to a known employer"),
        "amount": _f("number", "Receipt amount (authority currency)"),
        "age_days": _f("int", "Days since receipt posted"),
    },
}

FACT_SCHEMA["account_period"] = {
    "anchor_period": _f("bool", "Latest due period for this account (for repeat-pattern rules)"),
    "obligation_status": _f("enum", "Obligation status for the head and period", values=OBLIGATION_STATUSES),
    "pattern": _f(
        "enum",
        "Obligation pattern of the revenue head",
        values=[
            "monthly_return_payment",
            "annual_return_payment",
            "annual_demand",
            "licence_renewal",
            "transaction",
            "annual_levy",
        ],
    ),
    "subject_type": _f(
        "enum",
        "What the account is",
        values=["individual", "agent", "operator", "property", "premises", "vehicle", "business"],
    ),
    "use_class": _f(
        "enum",
        "Use class of a property, vehicle or premises",
        values=["residential", "commercial", "mixed", "industrial", "institutional", "private", "unknown"],
    ),
    "period_closed": _f("bool", "The period (month or tax year) has ended at evaluation time"),
    "return_required": _f("bool", "The pattern requires the taxpayer to file a return or declaration"),
    "return_due_at": _f("datetime", "Return / declaration due date", nullable=True),
    "return_due_passed": _f("bool", "Return / declaration due date has passed"),
    "filed_count": _f("int", "Returns or declarations filed and not rejected"),
    "filed_at": _f("datetime", "Earliest filing timestamp", nullable=True),
    "filing_late_days": _f("int", "Days filed after the due date", nullable=True),
    "transaction_count": _f("int", "Recorded taxable transactions in the period (registry evidence)"),
    "demand_issued": _f("bool", "A demand notice or levy bill has been issued"),
    "demand_served": _f("bool", "A demand notice has been lawfully served"),
    "liability_established": _f(
        "bool",
        "A liability exists: return filed, demand served, levy due, renewal due or transaction recorded",
    ),
    "liability_amount": _f(
        "number", "Declared, demanded or billed amount (authority currency)", nullable=True
    ),
    "payment_due_at": _f("datetime", "Payment / renewal due date", nullable=True),
    "payment_due_passed": _f("bool", "Payment / renewal due date has passed"),
    "paid_total": _f("number", "Settled, non-reversed payments allocated to the account and period"),
    "settled_payment_count": _f("int", "Settled, non-reversed payments allocated to the account and period"),
    "first_payment_at": _f("datetime", "Earliest settled payment", nullable=True),
    "payment_late_days": _f("int", "Days the earliest payment posted after the due date", nullable=True),
    "residual_amount": _f("number", "Liability minus payments (authority currency)", nullable=True),
    "reversal_pending": _f("bool", "A payment reversal awaits treasury confirmation"),
    "possible_unallocated_receipt": _f(
        "bool", "Unallocated receipts under this head may belong to the account"
    ),
    "legal_hold": _f("bool", "Appeal, stay or officer legal hold"),
    "disputed": _f("bool", "Taxpayer dispute recorded"),
}
FACT_SCHEMA["taxpayer_profile"] = {
    "taxpayer_type": _f(
        "enum", "Register type", values=["company", "individual", "partnership", "government", "ngo"]
    ),
    "income_indicator_count": _f(
        "int", "Active accounts that indicate business income: premises, commercial property or vehicles"
    ),
    "income_indicator_heads": _f("string", "Heads with income indicators, e.g. BPR, LUC"),
    "taxpayer_status": _f(
        "enum", "Register status", values=["active", "inactive", "dormant", "deregistered"]
    ),
    "has_direct_assessment_account": _f("bool", "A direct-assessment account exists for the individual"),
    "tax_year": _f("string", "Latest tax year whose direct-assessment return due date has passed"),
    "tax_year_due_passed": _f("bool", "A direct-assessment return due date has passed in the window"),
    "direct_assessment_filed": _f("bool", "A direct-assessment return was filed for that tax year"),
    "legal_hold": _f("bool", "Officer legal hold"),
    "disputed": _f("bool", "Taxpayer dispute recorded"),
}

HISTORY_SERIES = {"employer_period": ["filing", "payment"], "account_period": ["filing", "payment"]}
HISTORY_FIELDS: dict[str, FieldType] = {"eligible": "bool", "missing": "bool", "late": "bool"}

QUALITY_FIELDS = {
    "identity_verified": "bool",
    "match_confidence": "number",
    "staleness_days": "int",
    "freshness_sla_days": "int",
    "coverage": "object",
}


def field_spec(kind: str, field: str) -> FieldSpec | None:
    return FACT_SCHEMA.get(kind, {}).get(field)
