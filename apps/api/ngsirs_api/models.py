"""Canonical data model (Tech Spec section 5).

Every taxpayer-linked table carries ``tenant_id`` and is protected by Postgres
row-level security (see the initial migration). Canonical rows are versioned by
ingest batch: a newer batch supersedes the current row for the same natural key
and a rollback restores it, so nothing in a system-of-record extract is ever
silently altered.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True)


def now_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


Money = Numeric(18, 2)


# --- Governance -----------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    hosting_mode: Mapped[str] = mapped_column(String(32), default="state_hosted_single_tenant")
    legal_config_version: Mapped[str | None] = mapped_column(String(64))
    is_test_only: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = now_col()


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("tenant_id", "username"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    username: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String))
    unit: Mapped[str | None] = mapped_column(String(100))
    lga_scope: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    allowed_purposes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    seq: Mapped[int] = mapped_column(BigInteger)
    actor_id: Mapped[str] = mapped_column(String(100))
    actor_roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    subject_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    purpose: Mapped[str | None] = mapped_column(String(80))
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (UniqueConstraint("tenant_id", "actor_id", "key"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    actor_id: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = now_col()


class RetentionPolicy(Base):
    __tablename__ = "retention_policy"
    __table_args__ = (UniqueConstraint("tenant_id", "data_class"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    data_class: Mapped[str] = mapped_column(String(80))
    retain_days: Mapped[int] = mapped_column(Integer)
    legal_basis: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(32), default="review_then_delete")
    approved_by: Mapped[str | None] = mapped_column(String(100))


# --- Reference --------------------------------------------------------------------


class Lga(Base):
    __tablename__ = "lga"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(100))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    pilot: Mapped[bool] = mapped_column(Boolean, default=False)


class TaxOffice(Base):
    __tablename__ = "tax_office"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    lga_code: Mapped[str] = mapped_column(String(16))


# --- Ingestion & provenance -----------------------------------------------------------


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = (UniqueConstraint("tenant_id", "source_name"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_name: Mapped[str] = mapped_column(String(100))
    feed_types: Mapped[list[str]] = mapped_column(ARRAY(String))
    system_of_record: Mapped[bool] = mapped_column(Boolean, default=True)
    data_sharing_basis: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(200))
    permitted_purpose: Mapped[str] = mapped_column(Text)
    freshness_sla_days: Mapped[int] = mapped_column(Integer, default=7)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class IngestBatch(Base):
    __tablename__ = "ingest_batch"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    seq: Mapped[int] = mapped_column(BigInteger, server_default=text("nextval('ingest_batch_seq')"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_source.id"))
    feed_type: Mapped[str] = mapped_column(String(40), index=True)
    schema_version: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(300))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    manifest_signature: Mapped[str] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = now_col()
    coverage_from: Mapped[str | None] = mapped_column(String(7))
    coverage_to: Mapped[str | None] = mapped_column(String(7))
    coverage_lga: Mapped[str | None] = mapped_column(String(16))
    qa_status: Mapped[str] = mapped_column(String(20), default="received")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    field_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    committed_by: Mapped[str | None] = mapped_column(String(100))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_by: Mapped[str | None] = mapped_column(String(100))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_batch_content",
            "tenant_id",
            "source_id",
            "feed_type",
            "content_hash",
            unique=True,
            postgresql_where=text("qa_status <> 'rolled_back'"),
        ),
    )


class SourceRecord(Base):
    __tablename__ = "source_record"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingest_batch.id"), index=True)
    feed_type: Mapped[str] = mapped_column(String(40))
    row_number: Mapped[int] = mapped_column(Integer)
    natural_id: Mapped[str | None] = mapped_column(String(200), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20))  # accepted | quarantined | rejected | duplicate
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    messages: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    employer_ref: Mapped[str | None] = mapped_column(String(100), index=True)
    resolution: Mapped[str | None] = mapped_column(String(40))
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceCoverage(Base):
    __tablename__ = "source_coverage"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    feed_type: Mapped[str] = mapped_column(String(40))
    period_code: Mapped[str] = mapped_column(String(7))
    scope_lga: Mapped[str | None] = mapped_column(String(16))
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingest_batch.id"))
    complete: Mapped[bool] = mapped_column(Boolean, default=True)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)


class _Canonical:
    """Mixin for batch-versioned canonical rows."""

    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    superseded_by_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# --- Identity -----------------------------------------------------------------------------


class Taxpayer(_Canonical, Base):
    __tablename__ = "taxpayer"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_taxpayer_id: Mapped[str] = mapped_column(String(64), index=True)
    taxpayer_type: Mapped[str] = mapped_column(String(32))
    legal_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    name_token: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(200))
    jurisdiction_code: Mapped[str] = mapped_column(String(16))
    lga_code: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class TaxpayerIdentifier(Base):
    __tablename__ = "taxpayer_identifier"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayer.id"), index=True)
    identifier_type: Mapped[str] = mapped_column(String(32))
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    token: Mapped[str] = mapped_column(String(64), index=True)
    masked: Mapped[str] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class Employer(_Canonical, Base):
    __tablename__ = "employer"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_employer_id: Mapped[str] = mapped_column(String(64), index=True)
    linked_taxpayer_ref: Mapped[str | None] = mapped_column(String(64))
    taxpayer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    activity_from: Mapped[date | None] = mapped_column(Date)
    activity_to: Mapped[date | None] = mapped_column(Date)
    office_code: Mapped[str | None] = mapped_column(String(32))
    lga_code: Mapped[str | None] = mapped_column(String(16))
    sector: Mapped[str | None] = mapped_column(String(64))
    segment: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))


class IdentityMatch(Base):
    __tablename__ = "identity_match"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    taxpayer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    match_type: Mapped[str] = mapped_column(String(20))  # deterministic | probabilistic | manual
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(20)
    )  # auto_linked | pending_review | confirmed | rejected | retracted
    method_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reviewer: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_col()


# --- Legal obligations ---------------------------------------------------------------------


class LegalInstrument(Base):
    __tablename__ = "legal_instrument"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    authority: Mapped[str] = mapped_column(String(200))
    jurisdiction: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(40))
    source_note: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class LegalRuleVersion(Base):
    __tablename__ = "legal_rule_version"
    __table_args__ = (UniqueConstraint("tenant_id", "code", "version"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(32))
    tax_type: Mapped[str] = mapped_column(String(32))
    obligation_type: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_instrument.id"))
    provision_ref: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))  # draft | pending_approval | approved | retired
    drafted_by: Mapped[str] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = now_col()


class TaxObligation(_Canonical, Base):
    __tablename__ = "tax_obligation"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    natural_key: Mapped[str] = mapped_column(String(200), index=True)
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    taxpayer_ref: Mapped[str] = mapped_column(String(64))
    tax_type: Mapped[str] = mapped_column(String(32))
    obligation_type: Mapped[str] = mapped_column(String(64))
    legal_code: Mapped[str] = mapped_column(String(80))
    statutory_version: Mapped[str | None] = mapped_column(String(32))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    exemption_status: Mapped[str] = mapped_column(String(32), default="none")
    status: Mapped[str] = mapped_column(String(32))


class PeriodSchedule(Base):
    __tablename__ = "period_schedule"
    __table_args__ = (UniqueConstraint("tenant_id", "legal_code", "period_code"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    tax_type: Mapped[str] = mapped_column(String(32))
    obligation_type: Mapped[str] = mapped_column(String(64))
    legal_code: Mapped[str] = mapped_column(String(80))
    period_code: Mapped[str] = mapped_column(String(7))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    legal_rule_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_rule_version.id"))


class Extension(_Canonical, Base):
    __tablename__ = "extension"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    natural_key: Mapped[str] = mapped_column(String(200), index=True)
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    employer_ref: Mapped[str] = mapped_column(String(64))
    obligation_type: Mapped[str] = mapped_column(String(64))
    period_code: Mapped[str] = mapped_column(String(7))
    new_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))  # approved | pending | refused
    approved_by: Mapped[str | None] = mapped_column(String(100))


# --- Returns & payments ---------------------------------------------------------------------


class ReturnFiling(_Canonical, Base):
    __tablename__ = "return_filing"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    natural_key: Mapped[str] = mapped_column(String(200), index=True)
    source_name: Mapped[str] = mapped_column(String(100))
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    employer_ref: Mapped[str] = mapped_column(String(64))
    tax_type: Mapped[str] = mapped_column(String(32))
    period_code: Mapped[str] = mapped_column(String(7), index=True)
    filing_reference: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32))
    amount_declared: Mapped[Decimal | None] = mapped_column(Money)
    employee_count: Mapped[int | None] = mapped_column(Integer)


class Assessment(_Canonical, Base):
    __tablename__ = "assessment"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    natural_key: Mapped[str] = mapped_column(String(200), index=True)
    assessment_ref: Mapped[str] = mapped_column(String(64))
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    employer_ref: Mapped[str] = mapped_column(String(64))
    period_code: Mapped[str] = mapped_column(String(7))
    assessment_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Money)
    served_on: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    appeal_status: Mapped[str] = mapped_column(String(32))
    outstanding_amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(32))


class Payment(_Canonical, Base):
    __tablename__ = "payment"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    natural_key: Mapped[str] = mapped_column(String(200), index=True)
    payment_reference: Mapped[str] = mapped_column(String(64))
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    employer_ref: Mapped[str | None] = mapped_column(String(64))
    tax_type: Mapped[str] = mapped_column(String(32))
    period_code: Mapped[str | None] = mapped_column(String(7))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Money)
    reversal_status: Mapped[str] = mapped_column(String(32))  # none | reversed | reversal_pending
    settlement_status: Mapped[str] = mapped_column(String(32))  # settled | pending
    allocation_status: Mapped[str] = mapped_column(String(32))  # allocated | unallocated | suspense
    bank_delay_dispute: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_adjustment: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class PaymentAllocation(Base):
    __tablename__ = "payment_allocation"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment.id"), index=True)
    employer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    period_code: Mapped[str] = mapped_column(String(7))
    allocated_amount: Mapped[Decimal] = mapped_column(Money)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Rule management ------------------------------------------------------------------------


class RuleDefinitionRow(Base):
    __tablename__ = "rule_definition"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    rule_code: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    catalogue_status: Mapped[str] = mapped_column(String(32))  # pilot | proposed_r1 | retired
    legacy_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    default_treatment: Mapped[str | None] = mapped_column(String(64))
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class RuleVersion(Base):
    __tablename__ = "rule_version"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", "version"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    rule_code: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(16))
    expression_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    legal_ref: Mapped[str | None] = mapped_column(String(120))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    # draft | validated | pending_approval | approved | active | retired | rejected
    status: Mapped[str] = mapped_column(String(32))
    author_id: Mapped[str] = mapped_column(String(100))
    change_note: Mapped[str | None] = mapped_column(Text)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    backtest_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approvals: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    activated_by: Mapped[str | None] = mapped_column(String(100))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = now_col()


# --- Risk evaluation ------------------------------------------------------------------------


class InputSnapshot(Base):
    __tablename__ = "input_snapshot"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    batch_ids: Mapped[list[Any]] = mapped_column(JSONB)
    facts_hash: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(300))
    record_count: Mapped[int] = mapped_column(Integer)
    period_from: Mapped[str] = mapped_column(String(7))
    period_to: Mapped[str] = mapped_column(String(7))
    created_at: Mapped[datetime] = now_col()


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mode: Mapped[str] = mapped_column(String(20))  # operational | shadow | backtest | reproduce
    rule_set_hash: Mapped[str] = mapped_column(String(64))
    rule_version_ids: Mapped[list[Any]] = mapped_column(JSONB)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("input_snapshot.id"))
    period_from: Mapped[str] = mapped_column(String(7))
    period_to: Mapped[str] = mapped_column(String(7))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    outcome_digest: Mapped[str | None] = mapped_column(String(64))
    triggered_by: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = now_col()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiskSignal(Base):
    __tablename__ = "risk_signal"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"), index=True)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    rule_code: Mapped[str] = mapped_column(String(16))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(100))
    period_code: Mapped[str | None] = mapped_column(String(7))
    outcome: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    data_confidence: Mapped[float | None] = mapped_column(Float)


class RiskFinding(Base):
    __tablename__ = "risk_finding"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    finding_ref: Mapped[str] = mapped_column(String(40), unique=True)
    finding_key: Mapped[str] = mapped_column(String(200), index=True)
    rule_code: Mapped[str] = mapped_column(String(16), index=True)
    rule_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_version.id"))
    rule_version: Mapped[str] = mapped_column(String(16))
    legal_rule_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    legal_version_label: Mapped[str | None] = mapped_column(String(120))
    tax_type: Mapped[str] = mapped_column(String(32))
    domain: Mapped[str] = mapped_column(String(32))
    signal_class: Mapped[str] = mapped_column(String(32), index=True)
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(100), index=True)
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    employer_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    lga_code: Mapped[str | None] = mapped_column(String(16), index=True)
    period_code: Mapped[str | None] = mapped_column(String(7), index=True)
    likelihood: Mapped[int | None] = mapped_column(Integer)
    consequence: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[int | None] = mapped_column(Integer)
    priority_band: Mapped[str | None] = mapped_column(String(32))
    priority_note: Mapped[str | None] = mapped_column(String(64))
    effort: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), index=True)
    data_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    holds: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    treatment: Mapped[str | None] = mapped_column(String(64))
    allowed_next_action: Mapped[str | None] = mapped_column(String(64))
    explanation: Mapped[str] = mapped_column(Text)
    alternative_explanations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    matched_conditions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_run.id"))
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("input_snapshot.id"))
    first_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    last_seen_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    override: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = now_col()
    updated_at: Mapped[datetime] = now_col()
    __table_args__ = (
        Index("uq_finding_key_rule_version", "tenant_id", "finding_key", "rule_version_id", unique=True),
    )


class RiskEvidence(Base):
    __tablename__ = "risk_evidence"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_finding.id"), index=True)
    source_record_ref: Mapped[str] = mapped_column(String(200), index=True)
    field_name: Mapped[str | None] = mapped_column(String(80))
    snapshot_value: Mapped[str | None] = mapped_column(Text)
    value_hash: Mapped[str | None] = mapped_column(String(64))


class FindingEvent(Base):
    __tablename__ = "finding_event"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_finding.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = now_col()


# --- Compliance operation -------------------------------------------------------------------


class CaseRecord(Base):
    __tablename__ = "case_record"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    case_ref: Mapped[str] = mapped_column(String(40), unique=True)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_finding.id"), index=True)
    finding_key: Mapped[str] = mapped_column(String(200))
    employer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    employer_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    treatment: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(32), index=True)
    decision: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(64))
    assigned_to: Mapped[str | None] = mapped_column(String(100), index=True)
    created_by: Mapped[str] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_days: Mapped[int] = mapped_column(Integer, default=14)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    outward_permitted: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = now_col()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "uq_active_case_per_finding_key",
            "tenant_id",
            "finding_key",
            unique=True,
            postgresql_where=text("stage NOT IN ('closed','rejected')"),
        ),
    )


class CaseAction(Base):
    __tablename__ = "case_action"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_record.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    template_code: Mapped[str | None] = mapped_column(String(64))
    delivery_status: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    evidence_ref: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str | None] = mapped_column(String(64))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acted_at: Mapped[datetime] = now_col()


class EvidencePacket(Base):
    __tablename__ = "evidence_packet"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_record.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(Text)
    key_id: Mapped[str] = mapped_column(String(64))
    exported_by: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(80))
    object_key: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = now_col()


# --- Analytics & programmes -----------------------------------------------------------------


class Programme(Base):
    __tablename__ = "programme"
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    population: Mapped[dict[str, Any]] = mapped_column(JSONB)
    denominator_definition: Mapped[str] = mapped_column(Text)
    baseline_from: Mapped[str] = mapped_column(String(7))
    baseline_to: Mapped[str] = mapped_column(String(7))
    evaluation_from: Mapped[str] = mapped_column(String(7))
    evaluation_to: Mapped[str] = mapped_column(String(7))
    intervention: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    resource_budget: Mapped[str | None] = mapped_column(Text)
    comparison_share: Mapped[float] = mapped_column(Float, default=0.3)
    status: Mapped[str] = mapped_column(String(32))  # draft | approved | running | evaluated
    created_by: Mapped[str] = mapped_column(String(100))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = now_col()


class ProgrammeMember(Base):
    __tablename__ = "programme_member"
    __table_args__ = (UniqueConstraint("programme_id", "employer_id"),)
    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    programme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("programme.id"), index=True)
    employer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    group_name: Mapped[str] = mapped_column(String(20))  # intervention | comparison


TENANT_TABLES = [t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c]
