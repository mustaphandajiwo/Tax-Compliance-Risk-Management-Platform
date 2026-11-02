import type { ReactNode } from "react";
import type { Tone } from "./StatusBadge";

/** The explicit UI states required by the PRD (section 19) plus generic loading/error/forbidden. */
export type UiState =
  | "loading"
  | "no_data"
  | "invalid_import"
  | "insufficient_evidence"
  | "no_obligation"
  | "deferred"
  | "conflict"
  | "approved"
  | "closed"
  | "forbidden"
  | "error"
  | "info";

const DEFAULTS: Record<UiState, { title: string; tone: Tone; icon: string; alert?: boolean }> = {
  loading: { title: "Loading", tone: "neutral", icon: "" },
  no_data: { title: "No data", tone: "neutral", icon: "∅" },
  invalid_import: { title: "Invalid import", tone: "danger", icon: "×", alert: true },
  insufficient_evidence: { title: "Insufficient evidence", tone: "warning", icon: "!" },
  no_obligation: { title: "No verified obligation", tone: "warning", icon: "!" },
  deferred: { title: "Deferred", tone: "info", icon: "‖" },
  conflict: { title: "Conflict", tone: "danger", icon: "⇄", alert: true },
  approved: { title: "Approved", tone: "success", icon: "✓" },
  closed: { title: "Closed", tone: "neutral", icon: "■" },
  forbidden: { title: "Not permitted for your role", tone: "warning", icon: "⦸" },
  error: { title: "Something went wrong", tone: "danger", icon: "×", alert: true },
  info: { title: "Note", tone: "info", icon: "i" },
};

export interface StateMessageProps {
  state: UiState;
  title?: string;
  children?: ReactNode;
  /** Override the live-region politeness; errors/conflicts default to role=alert. */
  live?: "polite" | "assertive" | "off";
}

export function StateMessage({ state, title, children, live }: StateMessageProps) {
  const d = DEFAULTS[state];
  const role = live === "off" ? undefined : d.alert || live === "assertive" ? "alert" : "status";
  return (
    <div
      className={`ng-state ng-tone-${d.tone}${state === "loading" ? " ng-state--loading" : ""}`}
      role={role}
      data-state={state}
      aria-busy={state === "loading" ? true : undefined}
    >
      <span className="ng-state__icon" aria-hidden="true">
        {d.icon}
      </span>
      <div className="ng-state__body">
        <p className="ng-state__title">{title ?? d.title}</p>
        {children && <div className="ng-state__text">{children}</div>}
      </div>
    </div>
  );
}
