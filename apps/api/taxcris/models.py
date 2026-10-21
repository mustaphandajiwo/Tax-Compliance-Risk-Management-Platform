"""Persistent data model (PRD §12).

Conventions: every operational table carries ``tenant_id`` plus created/updated timestamps, UUID
primary keys, explicit source identifiers and provenance. Sensitive identifiers are stored only as
tenant-salted HMACs (``IdentityLink.hashed_identifier``) with a masked display hint.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


Money = Numeric(18, 2)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TenantScoped(TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state_code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_jurisdiction: Mapped[str] = mapped_column(String(100))
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    # Operational configuration: SLA days per intervention, feed staleness tolerance, etc.
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Per-tenant secret used to HMAC identifiers; never returned by the API.
    identifier_salt: Mapped[str] = mapped_column(String(64))
    # Hash-chain head for the tamper-evident audit log.
    audit_head_hash: Mapped[str] = mapped_column(String(64), default="0" * 64)
    audit_seq: Mapped[int] = mapped_column(Integer, default=0)


class User(TenantScoped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------------------------
# Ingestion and provenance
# ---------------------------------------------------------------------------------------------


class ImportBatch(TenantScoped, Base):
    __tablename__ = "import_batches"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    dataset: Mapped[str] = mapped_column(String(40))
    source_system: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    checksum: Mapped[str] = mapped_column(String(64))
    # Date the source system extracted the data; drives feed-freshness checks.
    extracted_at: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="received")
    total: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicate: Mapped[int] = mapped_column(Integer, default=0)
    quarantined: Mapped[int] = mapped_column(Integer, default=0)
    reconciliation_status: Mapped[str] = mapped_column(String(20), default="pending")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class ImportRecord(TenantScoped, Base):
    """Raw immutable landing zone row. ``raw`` is never updated after insert."""

    __tablename__ = "import_records"

    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON)
    raw_hash: Mapped[str] = mapped_column(String(64))
    source_record_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))  # accepted | rejected | duplicate | quarantined
    errors: Mapped[list] = mapped_column(JSON, default=list)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(String(40))


# ---------------------------------------------------------------------------------------------
# Taxpayer master
# ---------------------------------------------------------------------------------------------


class Taxpayer(TenantScoped, Base):
    __tablename__ = "taxpayers"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "source_record_id"),)

    taxpayer_type: Mapped[str] = mapped_column(String(20))  # individual | business
    name: Mapped[str] = mapped_column(String(250), index=True)
    registration_status: Mapped[str] = mapped_column(String(20))  # registered | unregistered | deregistered
    tax_residence: Mapped[str] = mapped_column(String(8))  # state code of residence/operation
    lga: Mapped[str | None] = mapped_column(String(80), index=True)
    sector: Mapped[str | None] = mapped_column(String(80), index=True)
    is_employer: Mapped[bool] = mapped_column(Boolean, default=False)
    self_employed: Mapped[bool] = mapped_column(Boolean, default=False)
    operating_status: Mapped[str] = mapped_column(String(20), default="active")  # active | dormant | closed
    closed_on: Mapped[date | None] = mapped_column(Date)
    registered_on: Mapped[date | None] = mapped_column(Date)
    source_system: Mapped[str] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(120))
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id"))
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("taxpayers.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    links: Mapped[list["IdentityLink"]] = relationship(back_populates="taxpayer", foreign_keys="IdentityLink.taxpayer_id")


class IdentityLink(TenantScoped, Base):
    __tablename__ = "identity_links"
    __table_args__ = (Index("ix_identity_hash", "tenant_id", "identifier_type", "hashed_identifier"),)

    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    identifier_type: Mapped[str] = mapped_column(String(20))  # TIN | NIN | CAC_RC | PHONE
    hashed_identifier: Mapped[str] = mapped_column(String(64))
    masked_value: Mapped[str] = mapped_column(String(40))
    match_confidence: Mapped[float] = mapped_column(default=1.0)
    source_ref: Mapped[str | None] = mapped_column(String(160))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    taxpayer: Mapped[Taxpayer] = relationship(back_populates="links", foreign_keys=[taxpayer_id])


class Employment(TenantScoped, Base):
    __tablename__ = "employments"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "source_record_id"),)

    employer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    monthly_gross: Mapped[Decimal | None] = mapped_column(Money)
    source_system: Mapped[str] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(120))


class MergeCandidate(TenantScoped, Base):
    __tablename__ = "merge_candidates"
    __table_args__ = (UniqueConstraint("tenant_id", "survivor_id", "duplicate_id"),)

    survivor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"))
    duplicate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"))
    confidence: Mapped[float] = mapped_column()
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|proposed|merged|rejected|rolled_back
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    # Rows moved from duplicate to survivor, retained so a merge can be rolled back exactly.
    moved: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------------------------
# Legal catalogue and obligations
# ---------------------------------------------------------------------------------------------


class LegalRule(TenantScoped, Base):
    __tablename__ = "legal_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "rule_code", "version"),)

    rule_code: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    jurisdiction: Mapped[str] = mapped_column(String(100))
    tax_type: Mapped[str] = mapped_column(String(20))  # PAYE | DA
    frequency: Mapped[str] = mapped_column(String(20))  # monthly | annual
    eligibility: Mapped[dict] = mapped_column(JSON, default=dict)
    deadline: Mapped[dict] = mapped_column(JSON)
    exemptions: Mapped[list] = mapped_column(JSON, default=list)
    evidence_requirements: Mapped[list] = mapped_column(JSON, default=list)
    citation: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|retired
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class TaxObligation(TenantScoped, Base):
    __tablename__ = "tax_obligations"
    __table_args__ = (UniqueConstraint("tenant_id", "taxpayer_id", "tax_type", "period"),)

    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM or YYYY
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    extension_until: Mapped[date | None] = mapped_column(Date)
    legal_rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("legal_rules.id"))
    rule_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|filed|filed_late|overdue|exempt


class TaxReturn(TenantScoped, Base):
    __tablename__ = "tax_returns"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "source_record_id"),)

    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_obligations.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10))
    filing_date: Mapped[date] = mapped_column(Date)
    reported_income: Mapped[Decimal] = mapped_column(Money)
    reported_amount: Mapped[Decimal] = mapped_column(Money)  # declared liability
    employee_count: Mapped[int | None] = mapped_column(Integer)
    source_system: Mapped[str] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(120))
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id"))


class Payment(TenantScoped, Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("tenant_id", "source_system", "source_record_id"),)

    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_obligations.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Money)
    payment_date: Mapped[date] = mapped_column(Date)
    allocation_status: Mapped[str] = mapped_column(String(20))  # allocated | unallocated | disputed
    channel: Mapped[str | None] = mapped_column(String(40))
    source_system: Mapped[str] = mapped_column(String(80))
    source_record_id: Mapped[str] = mapped_column(String(120))
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id"))


# ---------------------------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------------------------


class RiskModel(TenantScoped, Base):
    """A versioned, approvable scoring configuration (weights, thresholds) — the 'ruleset'."""

    __tablename__ = "risk_models"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)

    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    weights: Mapped[dict] = mapped_column(JSON)
    thresholds: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class RiskRun(TenantScoped, Base):
    __tablename__ = "risk_runs"

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_models.id"))
    model_version: Mapped[int] = mapped_column(Integer)
    engine_version: Mapped[str] = mapped_column(String(20))
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10))
    as_of: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    dataset_hash: Mapped[str | None] = mapped_column(String(64))
    assessed: Mapped[int] = mapped_column(Integer, default=0)
    alerts_created: Mapped[int] = mapped_column(Integer, default=0)
    suppressed: Mapped[int] = mapped_column(Integer, default=0)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class RiskAssessment(TenantScoped, Base):
    __tablename__ = "risk_assessments"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_runs.id"), index=True)
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10))
    model_version: Mapped[int] = mapped_column(Integer)
    ruleset_version: Mapped[str] = mapped_column(String(20))  # signal engine version
    obligation_versions: Mapped[dict] = mapped_column(JSON)  # rule_code -> version used
    evaluation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    inputs: Mapped[dict] = mapped_column(JSON)  # frozen snapshot used for scoring
    inputs_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    weights_applied: Mapped[dict] = mapped_column(JSON)
    dimension_scores: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column()
    confidence: Mapped[float] = mapped_column()
    confidence_components: Mapped[dict] = mapped_column(JSON)
    exposure_estimate: Mapped[Decimal] = mapped_column(Money)
    reason_codes: Mapped[list] = mapped_column(JSON)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("risk_assessments.id"))


class RiskSignal(TenantScoped, Base):
    __tablename__ = "risk_signals"

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_assessments.id"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_runs.id"), index=True)
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_obligations.id"))
    rule_id: Mapped[str] = mapped_column(String(60))  # signal rule code
    dimension: Mapped[str] = mapped_column(String(20))
    severity: Mapped[float] = mapped_column()
    confidence: Mapped[float] = mapped_column()
    exposure: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    reason_code: Mapped[str] = mapped_column(String(60))
    explanation: Mapped[str] = mapped_column(Text)
    is_hypothesis: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_ref: Mapped[dict] = mapped_column(JSON)
    safeguards: Mapped[list] = mapped_column(JSON, default=list)
    recommended_action: Mapped[str] = mapped_column(String(40))


# ---------------------------------------------------------------------------------------------
# Alerts, cases and interventions
# ---------------------------------------------------------------------------------------------


class Alert(TenantScoped, Base):
    __tablename__ = "alerts"

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("risk_assessments.id"))
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    tax_type: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|confirmed|dismissed|escalated|data_verification
    priority: Mapped[float] = mapped_column()
    triaged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    triage_reason: Mapped[str | None] = mapped_column(Text)
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Case(TenantScoped, Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("tenant_id", "reference"),)

    reference: Mapped[str] = mapped_column(String(30))
    taxpayer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("taxpayers.id"), index=True)
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sla_due: Mapped[date] = mapped_column(Date)
    proposed_intervention: Mapped[str | None] = mapped_column(String(40))
    disposition: Mapped[str | None] = mapped_column(String(40))
    outcome: Mapped[str | None] = mapped_column(Text)
    amount_collected: Mapped[Decimal | None] = mapped_column(Money)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseAction(TenantScoped, Base):
    __tablename__ = "case_actions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    justification: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Intervention(TenantScoped, Base):
    __tablename__ = "interventions"

    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|approved|returned|executed|rejected
    rationale: Mapped[str] = mapped_column(Text)
    proposed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------------------------
# Audit and jobs
# ---------------------------------------------------------------------------------------------


class AuditEvent(Base):
    """Append-only, hash-chained audit trail. Never updated or deleted by the application."""

    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("tenant_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(80), index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")  # success | denied | error
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))


class Job(TenantScoped, Base):
    __tablename__ = "jobs"

    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
