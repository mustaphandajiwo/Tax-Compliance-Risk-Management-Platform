"""Typed API contracts (exported to packages/contracts as OpenAPI 3.x)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorOut(BaseModel):
    detail: str


# --- auth ------------------------------------------------------------------------------------


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class TenantOut(ORM):
    id: uuid.UUID
    state_code: str
    name: str
    legal_jurisdiction: str
    config_version: int


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    permissions: list[str]
    tenant: TenantOut


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    mfa_enabled: bool


class UserCreate(BaseModel):
    email: str
    full_name: str = Field(min_length=2)
    role: str
    password: str = Field(min_length=12)


# --- imports ---------------------------------------------------------------------------------


class ImportIn(BaseModel):
    dataset: Literal["taxpayers", "employments", "returns", "payments"]
    source_system: str = Field(min_length=2, max_length=80)
    schema_version: str = "1.0"
    idempotency_key: str = Field(min_length=8, max_length=120)
    checksum: str = Field(min_length=64, max_length=64, description="sha256 of canonical JSON of `records`")
    extracted_at: date | None = None
    records: list[dict[str, Any]] = Field(max_length=50_000)


class ImportOut(ORM):
    id: uuid.UUID
    dataset: str
    source_system: str
    schema_version: str
    idempotency_key: str
    checksum: str
    extracted_at: date
    status: str
    total: int
    accepted: int
    rejected: int
    duplicate: int
    quarantined: int
    reconciliation_status: str
    created_at: datetime
    completed_at: datetime | None
    error: str | None
    job_id: uuid.UUID | None = None


class ImportRecordOut(ORM):
    id: uuid.UUID
    batch_id: uuid.UUID
    row_number: int
    source_record_id: str | None
    status: str
    errors: list[dict[str, Any]]
    target_type: str | None
    target_id: uuid.UUID | None
    resolution: str | None


# --- taxpayers -------------------------------------------------------------------------------


class IdentityLinkOut(BaseModel):
    identifier_type: str
    value: str  # masked unless caller holds taxpayers.read_sensitive
    match_confidence: float
    source_ref: str | None


class TaxpayerSummary(ORM):
    id: uuid.UUID
    taxpayer_type: str
    name: str
    registration_status: str
    lga: str | None
    sector: str | None
    is_employer: bool
    self_employed: bool
    operating_status: str
    latest_score: float | None = None
    latest_confidence: float | None = None


class ObligationOut(ORM):
    id: uuid.UUID
    tax_type: str
    period: str
    due_date: date
    extension_until: date | None
    rule_version: int
    legal_rule_id: uuid.UUID
    status: str


class ReturnOut(ORM):
    id: uuid.UUID
    tax_type: str
    period: str
    filing_date: date
    reported_income: Decimal
    reported_amount: Decimal
    employee_count: int | None
    source_system: str
    source_record_id: str


class PaymentOut(ORM):
    id: uuid.UUID
    tax_type: str
    period: str | None
    amount: Decimal
    payment_date: date
    allocation_status: str
    source_system: str
    source_record_id: str


class CaseSummary(ORM):
    id: uuid.UUID
    reference: str
    status: str
    taxpayer_id: uuid.UUID
    taxpayer_name: str | None = None
    sla_due: date
    proposed_intervention: str | None
    disposition: str | None
    assignee_id: uuid.UUID | None
    assignee_name: str | None = None
    sla_breached: bool = False
    created_at: datetime


class Taxpayer360(BaseModel):
    taxpayer: TaxpayerSummary
    tax_residence: str
    closed_on: date | None
    registered_on: date | None
    source: str
    merged_into_id: uuid.UUID | None
    identifiers: list[IdentityLinkOut]
    employer_links: list[dict[str, Any]]
    obligations: list[ObligationOut]
    returns: list[ReturnOut]
    payments: list[PaymentOut]
    assessments: list["AssessmentSummary"]
    cases: list[CaseSummary]


# --- legal rules -----------------------------------------------------------------------------


class LegalRuleIn(BaseModel):
    rule_code: str = Field(pattern=r"^[A-Z0-9_]{3,60}$")
    title: str
    jurisdiction: str
    tax_type: Literal["PAYE", "DA"]
    frequency: Literal["monthly", "annual"]
    eligibility: dict[str, Any] = {}
    deadline: dict[str, Any]
    exemptions: list[str] = []
    evidence_requirements: list[str] = []
    citation: str
    valid_from: date
    valid_to: date | None = None
    notes: str | None = None


class LegalRuleOut(ORM, LegalRuleIn):
    id: uuid.UUID
    version: int
    status: str
    created_by: uuid.UUID | None
    submitted_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None


class RuleTestIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")


class DecisionIn(BaseModel):
    reason: str = Field(min_length=5)


# --- risk ------------------------------------------------------------------------------------


class RiskModelIn(BaseModel):
    name: str
    weights: dict[str, float]
    thresholds: dict[str, float] = {}
    notes: str | None = None


class RiskModelOut(ORM):
    id: uuid.UUID
    version: int
    name: str
    weights: dict[str, float]
    thresholds: dict[str, float]
    status: str
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime


class RiskRunIn(BaseModel):
    tax_type: Literal["PAYE", "DA"]
    period: str = Field(pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$")
    model_version: int | None = Field(default=None, description="Defaults to the current approved model")
    as_of: date | None = None


class RiskRunOut(ORM):
    id: uuid.UUID
    model_version: int
    engine_version: str
    tax_type: str
    period: str
    as_of: date
    status: str
    dataset_hash: str | None
    assessed: int
    alerts_created: int
    suppressed: int
    job_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None
    error: str | None


class SignalOut(ORM):
    id: uuid.UUID
    rule_id: str
    dimension: str
    severity: float
    confidence: float
    exposure: Decimal
    reason_code: str
    explanation: str
    is_hypothesis: bool
    evidence_ref: dict[str, Any]
    safeguards: list[dict[str, Any]]
    recommended_action: str
    obligation_id: uuid.UUID | None


class AssessmentSummary(ORM):
    id: uuid.UUID
    run_id: uuid.UUID
    taxpayer_id: uuid.UUID
    taxpayer_name: str | None = None
    lga: str | None = None
    sector: str | None = None
    tax_type: str
    period: str
    model_version: int
    score: float
    confidence: float
    exposure_estimate: Decimal
    reason_codes: list[str]
    suppressed: bool
    evaluation_time: datetime
    superseded_by_id: uuid.UUID | None


class AssessmentDetail(AssessmentSummary):
    ruleset_version: str
    obligation_versions: dict[str, Any]
    inputs_hash: str
    output_hash: str
    weights_applied: dict[str, float]
    dimension_scores: dict[str, float | None]
    confidence_components: dict[str, float]
    suppression_reason: str | None
    signals: list[SignalOut] = []


class ReproduceOut(BaseModel):
    assessment_id: uuid.UUID
    inputs_hash_verified: bool
    stored_output_hash: str
    recomputed_output_hash: str
    reproducible: bool
    score: float


# --- alerts & cases --------------------------------------------------------------------------


class AlertOut(ORM):
    id: uuid.UUID
    assessment_id: uuid.UUID
    taxpayer_id: uuid.UUID
    taxpayer_name: str | None = None
    lga: str | None = None
    sector: str | None = None
    tax_type: str
    period: str
    status: str
    priority: float
    confidence: float | None = None
    exposure_estimate: Decimal | None = None
    reason_codes: list[str] = []
    triage_reason: str | None
    triaged_at: datetime | None
    case_id: uuid.UUID | None = None
    case_reference: str | None = None
    created_at: datetime


class TriageIn(BaseModel):
    decision: Literal["confirm", "dismiss", "escalate"]
    reason: str = Field(min_length=5)


class CaseCreate(BaseModel):
    alert_id: uuid.UUID
    justification: str = Field(min_length=5)


class CaseActionIn(BaseModel):
    action: str
    justification: str = Field(min_length=5)
    payload: dict[str, Any] = {}


class CaseActionOut(ORM):
    id: uuid.UUID
    action: str
    from_status: str
    to_status: str
    actor_id: uuid.UUID
    actor_name: str | None = None
    justification: str
    payload: dict[str, Any]
    created_at: datetime


class InterventionOut(ORM):
    id: uuid.UUID
    type: str
    status: str
    rationale: str
    proposed_by: uuid.UUID
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    execution_time: datetime | None
    outcome: str | None


class CaseDetail(CaseSummary):
    alert_id: uuid.UUID
    owner_id: uuid.UUID | None
    outcome: str | None
    amount_collected: Decimal | None
    closed_at: datetime | None
    available_actions: list[str]
    actions: list[CaseActionOut]
    interventions: list[InterventionOut]
    assessment: AssessmentDetail


# --- data quality ----------------------------------------------------------------------------


class MergeCandidateOut(ORM):
    id: uuid.UUID
    survivor_id: uuid.UUID
    duplicate_id: uuid.UUID
    survivor_name: str | None = None
    duplicate_name: str | None = None
    confidence: float
    reasons: list[str]
    status: str
    proposed_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    decided_at: datetime | None
    decision_reason: str | None


class MergeDecisionIn(BaseModel):
    decision: Literal["propose", "approve", "reject", "rollback"]
    reason: str = Field(min_length=5)


# --- audit -----------------------------------------------------------------------------------


class AuditEventOut(ORM):
    id: uuid.UUID
    seq: int
    timestamp: datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    details: dict[str, Any]
    prev_hash: str
    event_hash: str


class ChainVerification(BaseModel):
    valid: bool
    events_checked: int
    first_invalid_seq: int | None
    reason: str | None
    head_hash: str | None = None


Taxpayer360.model_rebuild()
