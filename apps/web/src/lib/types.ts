/**
 * Shapes for endpoints whose OpenAPI response is an untyped object
 * (`additionalProperties: true`). Kept narrow and optional where the backend may vary.
 */
import type { Schemas } from "./api";

export type Me = Schemas["MeOut"];
export type AlertOut = Schemas["AlertOut"];
export type AssessmentDetail = Schemas["AssessmentDetail"];
export type AssessmentSummary = Schemas["AssessmentSummary"];
export type SignalOut = Schemas["SignalOut"];
export type CaseDetail = Schemas["CaseDetail"];
export type CaseSummary = Schemas["CaseSummary"];
export type UserOut = Schemas["UserOut"];
export type ImportOut = Schemas["ImportOut"];
export type ImportRecordOut = Schemas["ImportRecordOut"];
export type MergeCandidateOut = Schemas["MergeCandidateOut"];
export type LegalRuleOut = Schemas["LegalRuleOut"];
export type LegalRuleIn = Schemas["LegalRuleIn"];
export type RiskModelOut = Schemas["RiskModelOut"];
export type RiskRunOut = Schemas["RiskRunOut"];
export type AuditEventOut = Schemas["AuditEventOut"];
export type Taxpayer360 = Schemas["Taxpayer360"];
export type TaxpayerSummary = Schemas["TaxpayerSummary"];

export type Freshness = Record<string, string | null>;

export interface Metric {
  key: string;
  label: string;
  definition: string;
  numerator: number | string | null;
  denominator: number | string | null;
  value: number | null;
  coverage: number | null;
  freshness?: Freshness;
  caution?: string;
  estimate_quality?: string;
  case_mix?: Record<string, number>;
  amount_collected?: string;
}

export interface LgaBreakdown {
  lga: string;
  numerator: number;
  denominator: number;
  value: number | null;
}

export interface MetricsResponse {
  metric_version: string;
  filters: { period: string | null; tax_type: string | null; lga: string | null; sector: string | null; as_of: string };
  freshness: Freshness;
  metrics: Metric[];
  breakdowns: {
    timely_filing_by_lga?: LgaBreakdown[];
    alerts_by_status?: Record<string, number>;
  };
}

export interface Connector {
  dataset: string;
  source_system: string;
  last_extracted_at: string | null;
  age_days: number | null;
  stale: boolean;
  last_batch_status: string | null;
  last_batch_id: string | null;
}

export interface DataQualitySummary {
  connectors: Connector[];
  record_status_counts: Record<string, number>;
  quarantined_open: number;
  merge_candidates: Record<string, number>;
  unreconciled_batches: number;
  stale_after_days: number;
}

export interface QuarantineItem {
  id: string;
  batch_id: string;
  dataset: string;
  source_system: string;
  row_number: number;
  source_record_id: string | null;
  errors: { field?: string; message?: string }[];
}

export interface RuleTestResult {
  rule_code: string;
  version: number;
  results: { period: string; due_date: string | null; this_version_valid: boolean; version_in_force: number | null }[];
}

export interface ModelTestResult {
  model_version: number;
  compared_to: number | null;
  sample_size: number;
  flagged_candidate: number;
  flagged_current: number;
  changed_flags: number;
  [k: string]: unknown;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Safeguard {
  check: string;
  result: string;
  detail?: string;
}
