"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { visibleNav } from "@/components/nav";
import { ActionResult, Badge, Card, ErrorBox, Loading, PageHead, SelectField, StatusBadge, TextField, useAction, useAsync } from "@/components/ui";
import { apiGet, downloadCsv } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, daysBetween, humanize, money, pct, PERIOD_RE, STALE_AFTER_DAYS } from "@/lib/format";
import { Datalist, SECTORS, TAX_TYPES } from "@/lib/reference";
import type { Freshness, Metric, MetricsResponse } from "@/lib/types";

interface Filters {
  period: string;
  tax_type: string;
  lga: string;
  sector: string;
}

const EMPTY: Filters = { period: "", tax_type: "", lga: "", sector: "" };

export default function OverviewPage() {
  const { me, can } = useAuth();
  const router = useRouter();
  const allowed = can("metrics.read");
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [periodError, setPeriodError] = useState<string | null>(null);
  const [view, setView] = useState<"bars" | "table">("bars");
  const exportAction = useAction();

  useEffect(() => {
    if (me && !allowed) {
      const first = visibleNav(me.permissions).find((n) => n.href !== "/");
      if (first) router.replace(first.href);
    }
  }, [me, allowed, router]);

  const metrics = useAsync(
    async () =>
      (await apiGet("/v1/metrics", {
        query: { period: filters.period, tax_type: filters.tax_type, lga: filters.lga, sector: filters.sector },
      })) as unknown as MetricsResponse,
    [filters.period, filters.tax_type, filters.lga, filters.sector],
    allowed,
  );
  const [lgaOptions, setLgaOptions] = useState<string[]>([]);
  useEffect(() => {
    const b = metrics.data?.breakdowns.timely_filing_by_lga;
    if (b && !filters.lga && lgaOptions.length === 0) setLgaOptions(b.map((x) => x.lga).sort());
  }, [metrics.data, filters.lga, lgaOptions.length]);

  if (!allowed) return <Loading label="Redirecting…" />;

  function apply(e: FormEvent) {
    e.preventDefault();
    if (draft.period && !PERIOD_RE.test(draft.period)) {
      setPeriodError("Use YYYY or YYYY-MM");
      return;
    }
    setPeriodError(null);
    setFilters(draft);
  }

  const data = metrics.data;
  const asOf = data?.filters.as_of;

  return (
    <>
      <PageHead
        title="Compliance overview"
        description="Approved metric definitions with numerator, denominator, coverage and source freshness. Aggregates only — no taxpayer-level data."
        actions={
          can("exports.aggregate") ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={exportAction.busy}
              onClick={() =>
                exportAction.run(
                  () =>
                    downloadCsv(
                      "/v1/exports/management-brief.csv",
                      { period: filters.period || undefined, tax_type: filters.tax_type || undefined, lga: filters.lga || undefined, sector: filters.sector || undefined },
                      `management-brief-${data?.filters.period ?? "current"}.csv`,
                    ),
                  "Management brief downloaded.",
                )
              }
            >
              {exportAction.busy ? "Preparing…" : "Download management brief (CSV)"}
            </button>
          ) : undefined
        }
      />
      <div className="stack">
        <ActionResult error={exportAction.error} success={exportAction.success} />
        <Card title="Filters">
          <form className="filters" onSubmit={apply} aria-label="Metric filters">
            <TextField label="Period" value={draft.period} onChange={(v) => setDraft({ ...draft, period: v })} placeholder={data?.filters.period ?? "YYYY or YYYY-MM"} hint="YYYY or YYYY-MM" error={periodError} />
            <SelectField label="Tax type" value={draft.tax_type} onChange={(v) => setDraft({ ...draft, tax_type: v })} options={[...TAX_TYPES]} allowEmpty emptyLabel="All" />
            <TextField label="LGA" value={draft.lga} onChange={(v) => setDraft({ ...draft, lga: v })} list="lga-options" placeholder="All LGAs" />
            <TextField label="Sector" value={draft.sector} onChange={(v) => setDraft({ ...draft, sector: v })} list="sector-options" placeholder="All sectors" />
            <div className="row">
              <button type="submit" className="btn btn-primary">
                Apply
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setDraft(EMPTY);
                  setFilters(EMPTY);
                  setPeriodError(null);
                }}
              >
                Reset
              </button>
            </div>
          </form>
          <Datalist id="lga-options" options={lgaOptions} />
          <Datalist id="sector-options" options={SECTORS} />
        </Card>

        {metrics.error && <ErrorBox error={metrics.error} onRetry={metrics.reload} />}
        {metrics.loading && !data && <Loading label="Computing metrics…" />}
        {data && (
          <div aria-busy={metrics.loading} className="stack">
            <p className="small muted mb-0" aria-live="polite">
              Showing period <strong>{data.filters.period ?? "all"}</strong>
              {data.filters.tax_type ? ` · ${data.filters.tax_type}` : " · all tax types"}
              {data.filters.lga ? ` · LGA ${data.filters.lga}` : ""}
              {data.filters.sector ? ` · ${data.filters.sector}` : ""} · as of {data.filters.as_of} · metric definitions v{data.metric_version}
            </p>
            <div className="grid-kpi">
              {data.metrics.map((m) => (
                <KpiTile key={m.key} metric={m} asOf={asOf} />
              ))}
            </div>
            <div className="grid-3">
              <Card title="Source freshness">
                <FreshnessTable freshness={data.freshness} asOf={asOf} />
              </Card>
              <Card
                title="Alerts by status"
                actions={
                  can("risk.read") ? (
                    <Link href="/workbench" className="small">
                      Open workbench
                    </Link>
                  ) : undefined
                }
              >
                <AlertsByStatus counts={data.breakdowns.alerts_by_status ?? {}} />
              </Card>
              <Card title="How to read these figures">
                <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
                  <li>Each tile shows numerator ÷ denominator and the share of records covered by complete data.</li>
                  <li>Revenue at risk is a scenario estimate from declared figures — not collectible debt.</li>
                  <li>Alerts are indicators for human review; low-confidence ones are referred for data verification.</li>
                  <li>Feeds older than {STALE_AFTER_DAYS} days are flagged stale and reduce confidence.</li>
                </ul>
              </Card>
            </div>
            <Card
              title="Timely filing by LGA"
              actions={
                <div className="row" role="group" aria-label="Display as">
                  <button type="button" className={`btn btn-sm ${view === "bars" ? "btn-primary" : ""}`} aria-pressed={view === "bars"} onClick={() => setView("bars")}>
                    Bars
                  </button>
                  <button type="button" className={`btn btn-sm ${view === "table" ? "btn-primary" : ""}`} aria-pressed={view === "table"} onClick={() => setView("table")}>
                    Table
                  </button>
                </div>
              }
            >
              <LgaBreakdown rows={data.breakdowns.timely_filing_by_lga ?? []} view={view} overall={data.metrics.find((m) => m.key === "timely_filing_rate")?.value ?? null} />
            </Card>
          </div>
        )}
      </div>
    </>
  );
}

function fraction(m: Metric): string {
  const isMoney = typeof m.numerator === "string" || typeof m.denominator === "string";
  const f = (v: number | string | null) => (v === null ? "—" : isMoney ? money(v) : count(v));
  if (m.denominator === null || m.denominator === undefined) return `Σ ${f(m.numerator)} (no denominator)`;
  return `${f(m.numerator)} ÷ ${f(m.denominator)}`;
}

function KpiTile({ metric: m, asOf }: { metric: Metric; asOf?: string }) {
  const isRate = m.denominator !== null && m.denominator !== undefined;
  const value = isRate ? pct(m.value) : money(m.value);
  const staleFeeds = Object.entries(m.freshness ?? {}).filter(([, d]) => !d || daysBetween(d, asOf) > STALE_AFTER_DAYS);
  const oldest = Object.values(m.freshness ?? {})
    .filter((d): d is string => !!d)
    .sort()[0];
  return (
    <section className="card kpi" aria-labelledby={`kpi-${m.key}`}>
      <div className="kpi-label">
        <span id={`kpi-${m.key}`}>{m.label}</span>
        {m.estimate_quality && <Badge tone="warn">Estimate quality: {m.estimate_quality}</Badge>}
      </div>
      <div className="kpi-value">{value}</div>
      {isRate && m.value !== null && (
        <div className="meter" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(1, m.value)) * 100}%` }} />
        </div>
      )}
      <div className="kpi-frac">{fraction(m)}</div>
      <div className="kpi-meta">
        <Badge tone={m.coverage !== null && m.coverage < 0.9 ? "warn" : "outline"}>Coverage {pct(m.coverage, 0)}</Badge>
        {oldest && <Badge tone={staleFeeds.length ? "danger" : "outline"}>Data to {oldest}</Badge>}
        {staleFeeds.length > 0 && <Badge tone="danger">Stale: {staleFeeds.map(([k]) => k).join(", ")}</Badge>}
      </div>
      {m.case_mix && (
        <div className="kpi-def">
          Case mix: {Object.entries(m.case_mix).map(([k, v]) => `${humanize(k)} ${v}`).join(", ")}
          {m.amount_collected ? ` · collected ${money(m.amount_collected)}` : ""}
        </div>
      )}
      <details>
        <summary className="tiny">Definition</summary>
        <p className="kpi-def mt-0">{m.definition}</p>
      </details>
      {m.caution && (
        <p className="tiny mb-0" style={{ color: "var(--warn)" }}>
          <strong>Caution:</strong> {m.caution}
        </p>
      )}
    </section>
  );
}

function FreshnessTable({ freshness, asOf }: { freshness: Freshness; asOf?: string }) {
  return (
    <table className="data">
      <thead>
        <tr>
          <th scope="col">Dataset</th>
          <th scope="col">Last extract</th>
          <th scope="col" className="num">
            Age
          </th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(freshness).map(([k, d]) => {
          const age = d ? daysBetween(d, asOf) : null;
          const stale = age === null || age > STALE_AFTER_DAYS;
          return (
            <tr key={k}>
              <td>{humanize(k)}</td>
              <td>{d ?? "never"}</td>
              <td className="num">{age === null ? "—" : `${age} d`}</td>
              <td>{stale ? <Badge tone="danger">Stale (&gt; {STALE_AFTER_DAYS} d)</Badge> : <Badge tone="ok">Fresh</Badge>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function AlertsByStatus({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return <p className="muted">No current alerts.</p>;
  return (
    <table className="data">
      <thead>
        <tr>
          <th scope="col">Status</th>
          <th scope="col" className="num">
            Alerts
          </th>
          <th scope="col" className="num">
            Share
          </th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(counts)
          .sort((a, b) => b[1] - a[1])
          .map(([s, n]) => (
            <tr key={s}>
              <td>
                <StatusBadge status={s} label={s === "data_verification" ? "Data verification (low confidence)" : undefined} />
              </td>
              <td className="num">{count(n)}</td>
              <td className="num">{pct(n / total, 0)}</td>
            </tr>
          ))}
        <tr>
          <th scope="row">Total</th>
          <td className="num">
            <strong>{count(total)}</strong>
          </td>
          <td />
        </tr>
      </tbody>
    </table>
  );
}

function LgaBreakdown({ rows, view, overall }: { rows: { lga: string; numerator: number; denominator: number; value: number | null }[]; view: "bars" | "table"; overall: number | null }) {
  if (!rows.length) return <p className="muted">No obligations past deadline for this selection.</p>;
  const sorted = [...rows].sort((a, b) => (a.value ?? 0) - (b.value ?? 0));
  if (view === "table") {
    return (
      <div className="table-wrap">
        <table className="data">
          <caption className="sr-only">Timely filing rate by local government area</caption>
          <thead>
            <tr>
              <th scope="col">LGA</th>
              <th scope="col" className="num">
                Filed on time
              </th>
              <th scope="col" className="num">
                Legally due
              </th>
              <th scope="col" className="num">
                Rate
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.lga}>
                <td>{r.lga}</td>
                <td className="num">{count(r.numerator)}</td>
                <td className="num">{count(r.denominator)}</td>
                <td className="num">{pct(r.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return (
    <div>
      <p className="small muted">
        Sorted lowest first. Vertical marker = state-wide rate ({pct(overall)}). Bars below 75% are shaded amber.
      </p>
      <div className="bars" role="list" aria-label="Timely filing rate by LGA">
        {sorted.map((r) => (
          <div key={r.lga} className="bar-row" role="listitem" aria-label={`${r.lga}: ${pct(r.value)} (${r.numerator} of ${r.denominator})`}>
            <span>{r.lga}</span>
            <div className="bar-track" aria-hidden="true">
              <div className={`bar-fill ${r.value !== null && r.value < 0.75 ? "low" : ""}`} style={{ width: `${(r.value ?? 0) * 100}%` }} />
              {overall !== null && <div className="bar-target" style={{ left: `${overall * 100}%` }} />}
            </div>
            <span className="small nowrap" aria-hidden="true">
              {pct(r.value)} <span className="muted">({r.numerator}/{r.denominator})</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
