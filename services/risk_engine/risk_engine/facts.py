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


class HistoryEntry(TypedDict, total=False):
    period: str
    eligible: bool
    missing: bool
    late: bool


class FactRecord(TypedDict, total=False):
    kind: str
    subject_type: str
    subject_id: str
    period: str | None
    tax_type: str
    facts: dict[str, Any]
    history: dict[str, list[HistoryEntry]]
    quality: dict[str, Any]
    evidence: dict[str, list[str]]
    legal_version: str | None


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
        "declared_payable": _f("number", "Payable declared on the accepted return (NGN)", nullable=True),
        "paid_allocated_total": _f("number", "Settled, non-reversed remittance allocated to the period"),
        "credits_adjustments_total": _f("number", "Approved credits/adjustments for the period"),
        "residual_amount": _f("number", "declared_payable - paid - credits (NGN)", nullable=True),
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
        "outstanding_amount": _f("number", "Net valid outstanding amount (NGN)"),
        "assessed_amount": _f("number", "Assessed amount (NGN)"),
        "employer_ref": _f("string", "Employer the assessment was raised against"),
        "legal_hold": _f("bool", "Appeal or stay in force"),
        "disputed": _f("bool", "Taxpayer dispute recorded"),
    },
    "taxpayer_pair": {
        "shared_identifier_count": _f("int", "Identifier tokens shared by the two records"),
        "name_similarity": _f("number", "Normalised name-token similarity 0-1"),
        "same_lga": _f("bool", "Both records are in the same LGA"),
    },
    "quarantined_record": {
        "feed_type": _f("string", "Feed the record came from"),
        "reason_code": _f("string", "Quarantine reason code"),
        "employer_known": _f("bool", "Row names a known employer"),
    },
    "payment_receipt": {
        "allocation_status": _f("enum", "Allocation status", values=["allocated", "unallocated", "suspense"]),
        "employer_matched": _f("bool", "Payment reference resolves to a known employer"),
        "amount": _f("number", "Receipt amount (NGN)"),
        "age_days": _f("int", "Days since receipt posted"),
    },
}

HISTORY_SERIES = {"employer_period": ["filing", "payment"]}
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
