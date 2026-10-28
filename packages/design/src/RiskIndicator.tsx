import { humanize, StatusBadge, statusTone } from "./StatusBadge";

export const RISK_LABEL = "Risk indicator, not finding of evasion";

export interface RiskIndicatorProps {
  priority: number | null;
  band: string | null;
  /** API priority_note: exposure_unknown | data_hold_no_score | null */
  note: string | null;
  confidence: number | null;
  likelihood?: number | null;
  consequence?: number | null;
  /** "compact" for table cells, "block" for detail pages. */
  variant?: "compact" | "block";
  /** Hide the inline label when the surrounding table/page already shows it prominently. */
  showLabel?: boolean;
  /** Hide confidence when a separate column already shows it (it is still never merged into the score). */
  showConfidence?: boolean;
}

/** Display text for a missing priority. Never renders 0 for an unknown score. */
export function priorityText(priority: number | null, note: string | null): string {
  if (priority !== null) return String(priority);
  if (note === "data_hold_no_score") return "Data hold – no score";
  if (note === "exposure_unknown") return "Exposure unknown";
  return note ? humanize(note) : "Not scored";
}

export function consequenceText(consequence: number | null | undefined, note: string | null): string {
  if (consequence !== null && consequence !== undefined) return String(consequence);
  return note === "data_hold_no_score" ? "Data hold – no score" : "Exposure unknown";
}

/**
 * Queue-ordering priority (4 x L x C) with its band, shown next to — never merged with — evidence confidence.
 */
export function RiskIndicator({
  priority,
  band,
  note,
  confidence,
  likelihood,
  consequence,
  variant = "compact",
  showLabel = true,
  showConfidence = true,
}: RiskIndicatorProps) {
  const text = priorityText(priority, note);
  return (
    <div className={`ng-risk ng-risk--${variant}`}>
      <div className="ng-risk__row">
        <span className="ng-risk__score">
          {variant === "block" && <span className="ng-visually-hidden">Priority index: </span>}
          {text}
        </span>
        {priority !== null && band && <StatusBadge status={band} tone={statusTone(band)} />}
        {priority === null && note === "data_hold_no_score" && <StatusBadge status="data_hold" />}
      </div>
      {showConfidence && (
        <span className="ng-risk__confidence">
          Confidence {confidence === null ? "unknown" : confidence.toFixed(2)}
        </span>
      )}
      {variant === "block" && (likelihood !== undefined || consequence !== undefined) && (
        <span className="ng-risk__confidence">
          Likelihood {likelihood ?? "—"} · Consequence {consequenceText(consequence, note)}
        </span>
      )}
      {showLabel && <span className="ng-risk__label">{RISK_LABEL}</span>}
    </div>
  );
}
