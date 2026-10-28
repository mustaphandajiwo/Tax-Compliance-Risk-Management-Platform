"""Request and response contracts. These drive the OpenAPI document and the generated TypeScript client."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class ErrorBody(Out):
    code: str
    message: str
    details: Any = None
    trace_id: str


class ErrorResponse(Out):
    error: ErrorBody


# --- auth ---------------------------------------------------------------------------


class DevTokenRequest(Model):
    username: str


class TokenResponse(Out):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int


class Me(Out):
    username: str
    display_name: str
    tenant: str
    tenant_name: str
    roles: list[str]
    permissions: list[str]
    purposes: list[str]
    lga_scope: list[str]
    environment: str
    synthetic_data: bool
    operating_mode: str


class DevUser(Out):
    username: str
    display_name: str
    roles: list[str]
    unit: str | None


# --- imports ------------------------------------------------------------------------


class ImportBatchOut(Out):
    id: str
    seq: int
    source: str | None
    feed_type: str
    file_name: str
    content_hash: str
    extracted_at: str
    ingested_at: str
    coverage: dict[str, Any]
    qa_status: str
    rows: int
    accepted: int
    quarantined: int
    rejected: int
    quality: dict[str, Any]
    created: bool | None = None


class RollbackRequest(Model):
    reason: str = Field(min_length=3)


class QuarantineResolution(Model):
    resolution: Literal["excluded", "corrected_at_source", "escalated"]
    note: str = Field(min_length=3)


class IdentityDecision(Model):
    decision: Literal["confirm", "reject", "retract"]
    reason: str = Field(min_length=3)


# --- legal --------------------------------------------------------------------------


class LegalVersionDraft(Model):
    code: str
    version: str
    instrument_code: str
    provision_ref: str
    jurisdiction: str = "NG-NI"
    effective_from: date
    effective_to: date | None = None
    parameters: dict[str, Any]
    is_synthetic: bool = True


class ApprovalNote(Model):
    note: str = Field(min_length=3)


# --- rules --------------------------------------------------------------------------


class RuleDraft(Model):
    definition: dict[str, Any]
    change_note: str = Field(min_length=3)


class RuleValidateRequest(Model):
    definition: dict[str, Any]


class BacktestRequest(Model):
    as_of: datetime
    period_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    period_to: str = Field(pattern=r"^\d{4}-\d{2}$")


class RuleApproval(Model):
    note: str = Field(min_length=3)
    as_role: Literal["legal_approver", "compliance_manager"]


class ReasonRequest(Model):
    reason: str = Field(min_length=3)


class EvaluationRequest(Model):
    as_of: datetime
    period_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    period_to: str = Field(pattern=r"^\d{4}-\d{2}$")


class EvaluationRunOut(Out):
    id: str
    mode: str
    status: str
    as_of: str
    period_from: str
    period_to: str
    rule_set_hash: str
    snapshot_hash: str | None
    rule_versions: list[str]
    counts: dict[str, Any]
    outcome_digest: str | None
    triggered_by: str
    started_at: str
    finished_at: str | None
    reused: bool | None = None


# --- findings -----------------------------------------------------------------------


class Indicators(Out):
    likelihood: int | None
    consequence: int | None
    confidence: float | None


class Gates(Out):
    identity_verified: bool
    legal_hold: bool
    data_hold: bool
    disputed: bool
    coverage_complete: bool | None


class FindingSummary(Out):
    finding_id: str
    finding_ref: str
    tenant_id: str
    rule: dict[str, str]
    title: str | None
    domain: str
    signal_class: str
    subject: dict[str, str | None]
    employer_name: str | None
    lga: str | None
    tax_type: str
    tax_period: str | None
    status: str
    indicators: Indicators
    priority_score: int | None
    priority_band: str | None
    priority_note: str | None
    flags: dict[str, bool]
    holds: list[str]
    treatment: str | None
    allowed_next_action: str | None
    explanation: str
    case: dict[str, Any] | None
    version: int
    created_at: str
    label: str = "Risk indicator, not finding of evasion"


class FindingDetail(FindingSummary):
    evidence_refs: list[str]
    gates: Gates
    legal_version: str | None
    matched_conditions: list[Any]
    alternative_explanations: list[str]
    evidence: list[dict[str, Any]]
    events: list[dict[str, Any]]
    override: dict[str, Any] | None
    rule_definition: dict[str, Any]
    snapshot: dict[str, Any]
    exclusions_checked: list[str]
    supersedes: str | None
    superseded_by: str | None
    signals: list[dict[str, Any]]


class FindingPage(Out):
    items: list[FindingSummary]
    total: int
    page: int
    page_size: int
    denominator_note: str


class ReviewRequest(Model):
    decision: Literal[
        "confirm",
        "not_substantiated",
        "corrected",
        "withdraw",
        "suppress",
        "return_to_review",
        "mark_disputed",
        "clear_disputed",
        "set_legal_hold",
        "clear_legal_hold",
        "refer_audit",
        "escalate",
    ]
    reason: str = Field(min_length=3)
    expected_version: int | None = None


class OverrideRequest(Model):
    likelihood: int | None = Field(default=None, ge=1, le=5)
    consequence: int | None = Field(default=None, ge=1, le=5)
    reason: str = Field(min_length=3)
    expected_version: int | None = None


# --- cases --------------------------------------------------------------------------


class CaseCreate(Model):
    finding_id: str
    treatment: str | None = None
    rationale: str = Field(min_length=3)
    assigned_to: str | None = None
    sla_days: int = Field(default=14, ge=1, le=180)


class CaseApprove(Model):
    note: str = Field(min_length=3)
    expected_version: int | None = None


class CaseAssign(Model):
    assignee: str
    expected_version: int | None = None


class CaseActionCreate(Model):
    action_type: str
    detail: str = Field(min_length=1)
    template_code: str | None = None
    evidence_ref: str | None = None
    outcome: str | None = None
    next_due_at: datetime | None = None
    expected_version: int | None = None


class CaseClose(Model):
    finding_outcome: Literal["closed_confirmed", "closed_not_substantiated", "corrected", "withdrawn"]
    note: str = Field(min_length=3)
    expected_version: int | None = None


class BatchApprove(Model):
    case_ids: list[str] = Field(min_length=1, max_length=200)
    note: str = Field(min_length=3)


class CaseOut(Out):
    id: str
    case_ref: str
    finding_id: str
    finding_ref: str | None
    rule_code: str | None
    employer_ref: str | None
    employer_name: str | None
    lga: str | None
    tax_period: str | None
    treatment: str
    treatment_label: str | None
    stage: str
    outcome: str | None
    assigned_to: str | None
    created_by: str
    approved_by: str | None
    approved_at: str | None
    due_at: str | None
    overdue: bool
    legal_hold: bool
    outward_permitted: bool
    outward_blockers: list[str]
    rationale: str
    version: int
    created_at: str


class CaseDetail(CaseOut):
    actions: list[dict[str, Any]]
    finding: FindingSummary | None
    packets: list[dict[str, Any]]


class EvidenceVerify(Model):
    packet: dict[str, Any]
    signature: str


# --- programmes ---------------------------------------------------------------------


class ProgrammeCreate(Model):
    code: str = Field(pattern=r"^[A-Z0-9-]{3,40}$")
    name: str
    objective: str
    population: dict[str, list[str]] = {}
    denominator_definition: str
    baseline_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    baseline_to: str = Field(pattern=r"^\d{4}-\d{2}$")
    evaluation_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    evaluation_to: str = Field(pattern=r"^\d{4}-\d{2}$")
    intervention: str
    target: str
    resource_budget: str | None = None
    comparison_share: float = Field(default=0.3, ge=0, le=0.5)
