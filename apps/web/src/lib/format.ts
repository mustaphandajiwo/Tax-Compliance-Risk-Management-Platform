/** Display helpers. Money and decimals arrive from the API as strings; never do arithmetic on them beyond display. */

const ngn = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 });
const int = new Intl.NumberFormat("en-NG");

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? ngn.format(n) : String(v);
}

export function count(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? int.format(n) : String(v);
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function date(v: string | null | undefined): string {
  if (!v) return "—";
  return v.slice(0, 10);
}

export function dateTime(v: string | null | undefined): string {
  if (!v) return "—";
  const s = v.replace("T", " ");
  return s.slice(0, 16);
}

export function humanize(v: string | null | undefined): string {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function shortId(v: string | null | undefined): string {
  return v ? v.slice(0, 8) : "—";
}

/** Whole days between an ISO date and an as-of date (default today). */
export function daysBetween(from: string, asOf?: string): number {
  const a = Date.parse(from.slice(0, 10));
  const b = asOf ? Date.parse(asOf.slice(0, 10)) : Date.now();
  return Math.floor((b - a) / 86_400_000);
}

export const STALE_AFTER_DAYS = 35;

export const PERIOD_RE = /^\d{4}(-(0[1-9]|1[0-2]))?$/;
