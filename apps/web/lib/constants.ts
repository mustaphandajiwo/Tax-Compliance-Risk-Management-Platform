import type { FindingOutcome, ReviewDecision } from "@ngsirs/contracts";

/** Controlled vocabularies mirrored from services/risk_engine/risk_engine/states.py and services/cases.py. */
export const FINDING_STATES = [
  "candidate",
  "validated",
  "review_required",
  "approved_for_treatment",
  "treated",
  "outcome_pending",
  "closed_confirmed",
  "closed_not_substantiated",
  "corrected",
  "withdrawn",
] as const;

export const CASE_STAGES = [
  "pending_approval",
  "approved",
  "in_progress",
  "awaiting_response",
  "outcome_recorded",
  "closed",
  "rejected",
] as const;

export const REVIEW_DECISIONS: { value: ReviewDecision; label: string; permission: string }[] = [
  { value: "confirm", label: "Confirm — approve for treatment", permission: "risks:review" },
  { value: "not_substantiated", label: "Not substantiated — close", permission: "risks:review" },
  { value: "corrected", label: "Corrected (data or record fixed)", permission: "risks:review" },
  { value: "withdraw", label: "Withdraw", permission: "risks:review" },
  { value: "suppress", label: "Suppress", permission: "risks:review" },
  { value: "return_to_review", label: "Return to review", permission: "risks:review" },
  { value: "mark_disputed", label: "Mark disputed", permission: "risks:review" },
  { value: "clear_disputed", label: "Clear disputed flag", permission: "risks:review" },
  { value: "set_legal_hold", label: "Set legal hold", permission: "risks:legal_hold" },
  { value: "clear_legal_hold", label: "Clear legal hold", permission: "risks:legal_hold" },
  { value: "refer_audit", label: "Refer for audit consideration", permission: "risks:review" },
  { value: "escalate", label: "Escalate", permission: "risks:review" },
];

export const ACTION_TYPES: { value: string; label: string }[] = [
  { value: "note", label: "Internal note" },
  { value: "contact_taxpayer", label: "Contact taxpayer (approved template)" },
  { value: "taxpayer_response", label: "Taxpayer response received" },
  { value: "payment_evidence_attached", label: "Payment evidence attached" },
  { value: "reconciliation_completed", label: "Reconciliation completed" },
  { value: "audit_finding", label: "Audit finding (audit officers only)" },
  { value: "escalate", label: "Escalate" },
  { value: "assistance_provided", label: "Assistance provided" },
];

export const APPROVED_TEMPLATES = [
  { code: "PAYE_RETURN_REMINDER_V1", label: "PAYE return reminder (v1)" },
  { code: "PAYE_ASSISTANCE_OFFER_V1", label: "PAYE assistance offer (v1)" },
  { code: "PAYE_PAYMENT_ENGAGEMENT_V1", label: "PAYE payment engagement (v1)" },
];

export const FINDING_OUTCOMES: { value: FindingOutcome; label: string }[] = [
  { value: "closed_confirmed", label: "Confirmed" },
  { value: "closed_not_substantiated", label: "Not substantiated" },
  { value: "corrected", label: "Corrected" },
  { value: "withdrawn", label: "Withdrawn" },
];

export const SIGNAL_CLASSES = ["taxpayer_risk", "data_quality", "debt_recovery"];
export const BANDS = ["low", "moderate", "high", "priority_review"];
export const HOLD_FILTERS = [
  { value: "data_hold", label: "Data hold" },
  { value: "legal_hold", label: "Legal hold" },
  { value: "disputed", label: "Disputed" },
  { value: "none", label: "No holds" },
];

export const OUTWARD_BLOCKERS: Record<string, string> = {
  treatment_is_internal: "Treatment is internal only",
  data_hold: "Finding is on data hold",
  legal_hold: "Legal hold applies",
  disputed: "Finding is disputed",
  identity_unverified: "Taxpayer identity not verified",
  data_quality_signal: "Data-quality signal (not a taxpayer risk)",
  shadow_mode: "Tenant is in shadow mode",
};
