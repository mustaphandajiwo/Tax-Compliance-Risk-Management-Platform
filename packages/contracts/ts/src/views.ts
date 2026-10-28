/**
 * Response shapes for endpoints whose OpenAPI schema is an open object (`{[key: string]: unknown}`).
 * Derived from apps/api/ngsirs_api/routers/*.py and serializers.py. Keep in step with the API until
 * those routes declare a response_model, then delete the matching type and use the generated one.
 */
import type { components } from "./schema";

/** Every dashboard figure carries its own numerator, denominator, window and completeness. */
export interface Metric {
  key: string;
  label: string;
  /** null when withheld (low completeness or empty denominator); the reason is in caveats. */
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  window: string;
  completeness: number | null;
  unit: "rate" | "NGN" | "days" | string;
  caveats: string[];
}

export interface SourceFreshness {
  source: string;
  feed_type: string;
  last_extracted_at: string | null;
  age_days: number | null;
  sla_days: number | null;
  stale: boolean;
}

export interface DashboardSummary {
  generated_at: string;
  synthetic_data: boolean;
  filters: { period: string | null; lga: string | null; tax_type: string };
  run: { id: string; as_of: string; rule_set_hash: string; periods: [string, string] } | null;
  metrics: Metric[];
  trend: { period: string; filing: Metric; remittance: Metric }[];
  by_lga: { lga: string; name: string; filing: Metric }[];
  findings: {
    open?: number;
    by_class?: Record<string, number>;
    by_rule?: Record<string, number>;
    by_band?: Record<string, number>;
    data_holds?: number;
    legal_holds?: number;
    disputed?: number;
  };
  cases: { by_stage?: Record<string, number>; overdue?: number; outward_permitted?: number };
  data_quality: {
    quarantined_unresolved?: number;
    identity_matches_pending?: number;
    sources?: SourceFreshness[];
  };
  method_note: string;
}

export interface Lga {
  code: string;
  name: string;
  verified: boolean;
  pilot: boolean;
}

export interface Reference {
  lgas: Lga[];
  offices: { code: string; name: string; lga: string }[];
  roles: Record<string, string>;
  purposes: Record<string, string>;
  treatments: Record<string, { label: string; human_gate: string; outward: boolean; approver_roles: string[] }>;
  users: { username: string; display_name: string; roles: string[]; unit: string | null }[];
}

// --- taxpayers ------------------------------------------------------------------------------

export interface TaxpayerSearchItem {
  employer_ref: string;
  name: string;
  lga: string | null;
  sector: string | null;
  segment: string | null;
  status: string;
  taxpayer_ref: string | null;
  identity: { status: string; confidence: number | null };
  duplicate_warning: string[];
  tax_types: string[];
  obligation_status: string;
  open_findings: number;
}

export interface TaxpayerSearchPage {
  items: TaxpayerSearchItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface PeriodStatus {
  period: string;
  obligation_status: string;
  return_due_at: string | null;
  accepted_at: string | null;
  filing_status: string;
  payment_status: string;
  declared_payable: number | null;
  paid: number | null;
  residual: number | null;
  legal_version: string | null;
  holds: string[];
}

export interface Taxpayer360 {
  employer: {
    ref: string;
    name: string;
    lga: string | null;
    office: string | null;
    sector: string | null;
    segment: string | null;
    status: string;
    activity_from: string | null;
    activity_to: string | null;
    source_record: string;
  };
  taxpayer: {
    ref: string;
    name: string;
    type: string;
    status: string;
    jurisdiction: string | null;
    lga: string | null;
    identifiers: { type: string; masked: string; verification: string }[];
  } | null;
  identity: {
    status: string;
    confidence: number | null;
    match_type: string | null;
    history: { status: string; type: string; confidence: number | null; reviewer: string | null; at: string }[];
  };
  duplicate_warning: string[];
  obligations: {
    tax_type: string;
    type: string;
    status: string;
    effective_from: string;
    effective_to: string | null;
    exemption: string | null;
    source: string;
  }[];
  obligation_summary: "no_obligation_record" | "recorded";
  periods: PeriodStatus[];
  filings: {
    ref: string;
    source: string;
    period: string;
    status: string;
    submitted_at: string | null;
    accepted_at: string | null;
    amount_declared: number | null;
  }[];
  payments: {
    ref: string;
    period: string | null;
    paid_at: string;
    amount: number;
    reversal_status: string;
    allocation_status: string;
    settlement_status: string;
  }[];
  assessments: {
    ref: string;
    period: string | null;
    amount: number;
    outstanding: number;
    status: string;
    appeal_status: string | null;
    served_on: string | null;
  }[];
  reporting_risk: { status: "unknown" | "evidence_available"; note: string };
  findings: components["schemas"]["FindingSummary"][];
  cases: { id: string; ref: string; stage: string; treatment: string }[];
  label: string;
}

export interface IdentifierReveal {
  identifiers: { type: string; value: string }[];
  purpose: string;
}

// --- findings & cases -----------------------------------------------------------------------

export interface ReproduceResult {
  reproduced: boolean;
  outcome_hash: string;
  stored_outcome_hash: string | null;
  rule: string;
  rule_content_hash: string | null;
  snapshot: string | null;
  run_id: string;
  rule_set_hash: string | null;
  outcome?: Record<string, unknown>;
}

export interface BatchApproveResult {
  approved: { case_id: string; case_ref: string; outward_permitted: boolean }[];
  skipped: { case_id: string; reason: string }[];
}

export interface EvidencePacketResult {
  packet: Record<string, unknown>;
  sha256: string;
  signature: string;
  key_id: string;
  algorithm: string;
}

// --- imports & data quality -----------------------------------------------------------------

export interface FeedColumn {
  name: string;
  type: string;
  required: boolean;
  values: string[];
  description: string;
}

export interface FeedTemplate {
  feed_type: string;
  title: string;
  description: string;
  safeguard: string;
  natural_key: string[];
  columns: FeedColumn[];
}

export interface DataSource {
  id: string;
  source_name: string;
  feed_types: string[];
  system_of_record: boolean;
  data_sharing_basis: string;
  owner: string;
  permitted_purpose: string;
  freshness_sla_days: number | null;
  is_external: boolean;
  enabled: boolean;
  freshness: (SourceFreshness | null)[];
}

export interface QuarantineItem {
  id: string;
  feed_type: string;
  batch_id: string;
  batch_seq: number | null;
  row_number: number;
  natural_id: string | null;
  employer_ref: string | null;
  reasons: string[];
  messages: string[];
  raw: Record<string, unknown>;
  resolution: string | null;
  resolved_by: string | null;
}

export interface IdentityMatchItem {
  id: string;
  employer_ref: string | null;
  employer_name: string | null;
  employer_lga: string | null;
  candidate_taxpayer: string | null;
  candidate_name: string | null;
  match_type: string;
  confidence: number | null;
  status: string;
  method: Record<string, unknown> | null;
  reviewer: string | null;
  reason: string | null;
}

export interface ImportRowsPage {
  total: number;
  page: number;
  items: {
    id: string;
    row_number: number;
    status: string;
    natural_id: string | null;
    reasons: string[];
    messages: string[];
    raw: Record<string, unknown>;
    resolution: string | null;
  }[];
}

// --- rules ------------------------------------------------------------------------------------

export interface RuleListItem {
  rule_code: string;
  domain: string;
  title: string;
  description: string;
  catalogue_status: "pilot" | "proposed_r1" | "implemented_as_gate" | "retired_merged" | string;
  legacy_codes: string[];
  default_treatment: string | null;
  active_version: string | null;
  active_since: string | null;
  versions: { id: string; version: string; status: string }[];
}

export interface RuleApprovalRecord {
  at: string;
  note: string;
  role: string;
  rule: string;
  actor: string;
  key_id: string;
  version: string;
  signature: string;
  content_hash: string;
}

export interface RuleVersion {
  id: string;
  rule_code: string;
  version: string;
  status: string;
  content_hash: string;
  legal_ref: string | null;
  author: string;
  change_note: string;
  approvals: RuleApprovalRecord[];
  activated_by: string | null;
  activated_at: string | null;
  validation: ValidationReport | null;
  backtest: BacktestResult | Record<string, unknown> | null;
  definition: Record<string, unknown>;
  created_at: string | null;
}

export interface RuleDetail {
  rule_code: string;
  domain: string;
  title: string;
  description: string;
  catalogue_status: string;
  legacy_codes: string[];
  active_version_id: string | null;
  versions: RuleVersion[];
}

export interface RuleDiff {
  rule_code: string;
  from: string;
  to: string;
  changes: { path: string; change: "added" | "removed" | "changed"; from?: unknown; to?: unknown }[];
}

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  warnings?: string[];
  [key: string]: unknown;
}

export interface BacktestSide {
  evaluated: number;
  findings: number;
  data_holds: number;
  suppressed: number;
  bands: Record<string, number>;
  by_lga: Record<string, number>;
}

export interface BacktestResult {
  rule: string;
  compared_with: string | null;
  as_of: string;
  periods: [string, string];
  candidate: BacktestSide;
  active: BacktestSide | null;
  newly_flagged: string[];
  no_longer_flagged: string[];
  newly_flagged_count: number;
  no_longer_flagged_count: number;
  generated_at: string;
  generated_by: string;
}

export interface RuleLanguage {
  fact_kinds: Record<string, Record<string, { type: string; nullable: boolean; description: string; values?: string[] }>>;
  history_series: unknown;
  history_fields: unknown;
  operators: string[];
  combinators: string[];
  eligibility: Record<string, { description: string; kinds: string[] }>;
  exclusions: Record<string, { description: string; kinds: string[] }>;
  holds: Record<string, { description: string; kinds: string[] }>;
  treatments: Record<string, { label: string; human_gate: string; outward: boolean }>;
}

export interface RunReproduceResult {
  run_id: string;
  reproduced: boolean;
  outcome_digest: string;
  stored_outcome_digest: string | null;
  snapshot: string | null;
  rule_versions: string[];
  [key: string]: unknown;
}

// --- legal ------------------------------------------------------------------------------------

export interface LegalVersion {
  id: string;
  code: string;
  version: string;
  tax_type: string;
  obligation_type: string;
  instrument: string | null;
  instrument_title: string | null;
  authority: string | null;
  provision_ref: string;
  jurisdiction: string;
  effective_from: string;
  effective_to: string | null;
  parameters: Record<string, unknown>;
  status: string;
  drafted_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_note: string | null;
  content_hash: string | null;
  is_synthetic: boolean;
}

export interface LegalObligations {
  codes: Record<string, { tax_type: string; obligation_type: string; required: string[] }>;
  versions: LegalVersion[];
  taxpayer_obligations_by_status: Record<string, number>;
  notice: string;
}

export interface LegalInstrument {
  id: string;
  code: string;
  title: string;
  authority: string;
  jurisdiction: string;
  status: string;
  source_note: string;
  is_synthetic: boolean;
}

export interface LegalResolve {
  code: string;
  period: string;
  approved_version: LegalVersion | null;
  unapproved_candidate: LegalVersion | null;
  due_at: string | null;
  status: "resolved" | "obligation_unverified";
}

// --- programmes -------------------------------------------------------------------------------

export interface ProgrammeEvaluation {
  programme: string;
  run_id: string;
  as_of: string;
  method: string;
  groups: Record<string, { members: number; baseline?: Metric; evaluation?: Metric }>;
  difference_in_differences: number | null;
  caveat?: string;
  evaluated_at: string;
}

export interface Programme {
  id: string;
  code: string;
  name: string;
  objective: string;
  population: Record<string, string[]>;
  denominator_definition: string;
  baseline: [string, string];
  evaluation_window: [string, string];
  intervention: string;
  target: string;
  resource_budget: string | null;
  comparison_share: number;
  status: string;
  created_by: string;
  approved_by: string | null;
  members: Record<string, number>;
  evaluation: ProgrammeEvaluation | null;
}

// --- reports & audit --------------------------------------------------------------------------

export interface ReportListItem {
  name: string;
  description: string;
  formats: string[];
}

export interface ReportResult {
  meta: {
    report: string;
    generated_at: string;
    generated_by: string;
    period: string | null;
    rows: number;
    method_note: string;
  };
  rows: Record<string, unknown>[];
}

export interface AuditEvent {
  seq: number;
  actor: string;
  roles: string[];
  event_type: string;
  subject: string;
  purpose: string | null;
  details: Record<string, unknown> | null;
  before_hash: string | null;
  after_hash: string | null;
  trace_id: string | null;
  occurred_at: string;
  event_hash: string;
  prev_hash: string | null;
}

export interface AuditPage {
  total: number;
  items: AuditEvent[];
}

export interface AuditVerify {
  valid: boolean;
  events: number;
  head_hash?: string;
  broken_at_seq?: number;
  reason?: string;
}
