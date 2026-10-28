import type { ReactNode } from "react";

export interface MetricFigures {
  key?: string;
  label: string;
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  window: string;
  completeness: number | null;
  unit: string;
  caveats: string[];
}

const intFmt = new Intl.NumberFormat("en-NG", { maximumFractionDigits: 0 });
const ngnFmt = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });

export function formatMetricValue(m: Pick<MetricFigures, "value" | "unit">): string {
  if (m.value === null) return "Withheld";
  if (m.unit === "rate") return `${(m.value * 100).toFixed(1)}%`;
  if (m.unit === "NGN") return ngnFmt.format(m.value);
  if (m.unit === "days") return `${m.value.toFixed(1)} days`;
  return intFmt.format(m.value);
}

function formatCount(n: number | null, unit: string): string {
  if (n === null) return unit === "rate" ? "None" : "Not applicable (amount, not a rate)";
  return unit === "NGN" ? ngnFmt.format(n) : intFmt.format(n);
}

/** Why a value is null, taken from the API's own caveats. */
export function withheldReason(m: MetricFigures): string {
  const c = m.caveats.find((x) => /withheld|no eligible population/i.test(x));
  return c ?? "Value withheld by the API: insufficient eligible population or data completeness.";
}

export interface MetricCardProps {
  metric: MetricFigures;
  /** Heading element for the card title, to fit the page outline. */
  headingLevel?: 2 | 3 | 4;
  footer?: ReactNode;
}

/**
 * A KPI that always shows how it was computed: numerator, denominator, time window,
 * data completeness and caveats. A withheld value (null) states the reason instead of a number.
 */
export function MetricCard({ metric, headingLevel = 3, footer }: MetricCardProps) {
  const H = `h${headingLevel}` as "h3";
  const withheld = metric.value === null;
  return (
    <article className="ng-metric" data-metric-key={metric.key}>
      <H className="ng-metric__title">{metric.label}</H>
      {withheld ? (
        <p className="ng-metric__withheld">
          Withheld<span className="ng-visually-hidden">:</span>{" "}
          <span style={{ fontSize: "var(--ng-text-sm)", fontWeight: 500, display: "block" }}>{withheldReason(metric)}</span>
        </p>
      ) : (
        <p className="ng-metric__value">{formatMetricValue(metric)}</p>
      )}
      <dl className="ng-metric__facts">
        <dt>Numerator</dt>
        <dd>{formatCount(metric.numerator, metric.unit)}</dd>
        <dt>Denominator</dt>
        <dd>{formatCount(metric.denominator, metric.unit)}</dd>
        <dt>Time window</dt>
        <dd>{metric.window || "—"}</dd>
        <dt>Completeness</dt>
        <dd>{metric.completeness === null ? "Not measured for this metric" : `${(metric.completeness * 100).toFixed(0)}%`}</dd>
      </dl>
      {metric.caveats.length > 0 && (
        <ul className="ng-metric__caveats" aria-label="Caveats">
          {metric.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      {footer}
    </article>
  );
}
