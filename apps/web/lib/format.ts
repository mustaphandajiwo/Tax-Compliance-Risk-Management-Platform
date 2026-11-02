export { humanize } from "@taxrisk/design";

/**
 * Locale settings of the signed-in authority (from its jurisdiction pack, via /me).
 * Defaults apply until a session loads; `configureLocale` is called by the auth provider.
 */
let locale = "en-NG";
let currency = "NGN";
let timeZone = "Africa/Lagos";
let fmts = build();

function build() {
  return {
    date: new Intl.DateTimeFormat("en-GB", { timeZone, day: "2-digit", month: "short", year: "numeric" }),
    dateTime: new Intl.DateTimeFormat("en-GB", {
      timeZone,
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }),
    money: new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 2 }),
    int: new Intl.NumberFormat(locale),
  };
}

export function configureLocale(opts: { locale?: string; currency?: string; timeZone?: string }) {
  locale = opts.locale ?? locale;
  currency = opts.currency ?? currency;
  timeZone = opts.timeZone ?? timeZone;
  fmts = build();
}

export function currentTimeZone(): string {
  return timeZone;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : fmts.date.format(d);
}

/** Date-time in the authority's operating time zone, with the zone shown. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : fmts.dateTime.format(d);
}

/** Money in the authority's currency. */
export function fmtMoney(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : fmts.money.format(n);
}

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : fmts.int.format(n);
}

/** Offset of `zone` at the given local wall-clock time, as "+01:00". */
export function zoneOffset(localIso: string, zone: string = timeZone): string {
  const guess = new Date(`${localIso.length === 16 ? `${localIso}:00` : localIso}Z`);
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
    .formatToParts(guess)
    .find((p) => p.type === "timeZoneName")?.value;
  const m = parts?.match(/GMT([+-]\d{2}):?(\d{2})?/);
  return m ? `${m[1]}:${m[2] ?? "00"}` : "+00:00";
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
