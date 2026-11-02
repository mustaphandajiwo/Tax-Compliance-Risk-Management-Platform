import type { ReactNode } from "react";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

/** Default tone for the controlled finding, case, import and version states used across the platform. */
const STATUS_TONES: Record<string, Tone> = {
  // findings (PRD section 14)
  candidate: "neutral",
  validated: "info",
  review_required: "warning",
  approved_for_treatment: "info",
  treated: "info",
  outcome_pending: "info",
  closed_confirmed: "neutral",
  closed_not_substantiated: "neutral",
  corrected: "neutral",
  withdrawn: "neutral",
  // cases
  pending_approval: "warning",
  approved: "success",
  in_progress: "info",
  awaiting_response: "info",
  outcome_recorded: "info",
  closed: "neutral",
  rejected: "danger",
  // imports / data quality
  committed: "success",
  rolled_back: "neutral",
  quarantined: "warning",
  pending_review: "warning",
  confirmed: "success",
  auto_linked: "success",
  retracted: "danger",
  // rules / legal / programmes
  draft: "neutral",
  active: "success",
  retired: "neutral",
  evaluated: "success",
  pending_legal_confirmation: "warning",
  // holds and flags
  data_hold: "warning",
  legal_hold: "warning",
  disputed: "warning",
  overdue: "danger",
  stale: "warning",
  // bands
  low: "neutral",
  moderate: "info",
  high: "warning",
  priority_review: "danger",
};

export function statusTone(status: string | null | undefined): Tone {
  return (status && STATUS_TONES[status]) || "neutral";
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export interface StatusBadgeProps {
  /** Machine status code; humanised for display unless children are given. */
  status?: string | null;
  tone?: Tone;
  children?: ReactNode;
  title?: string;
}

export function StatusBadge({ status, tone, children, title }: StatusBadgeProps) {
  const t = tone ?? statusTone(status);
  return (
    <span className={`ng-badge ng-tone-${t}`} title={title} data-status={status ?? undefined}>
      {children ?? humanize(status)}
    </span>
  );
}
