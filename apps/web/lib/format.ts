export { humanize } from "@ngsirs/design";

const TZ = "Africa/Lagos";

const dateFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: TZ,
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const ngnFmt = new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 2 });
const intFmt = new Intl.NumberFormat("en-NG");

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateFmt.format(d);
}

/** Date-time in West Africa Time (WAT), the NGSIRS operating timezone. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${dateTimeFmt.format(d)} WAT`;
}

export function fmtNGN(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : ngnFmt.format(n);
}

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : intFmt.format(n);
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${(n * 100).toFixed(digits)}%`;
}

export function fmtConfidence(n: number | null | undefined): string {
  return n === null || n === undefined ? "Unknown" : n.toFixed(2);
}

export function shortHash(h: string | null | undefined, len = 12): string {
  if (!h) return "—";
  return h.length > len ? `${h.slice(0, len)}…` : h;
}

/** Last N calendar months ending at `end` (YYYY-MM), oldest first. */
export function monthRange(endPeriod: string, count: number): string[] {
  const [y, m] = endPeriod.split("-").map(Number);
  const out: string[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(y, m - 1 - i, 1));
    out.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}
