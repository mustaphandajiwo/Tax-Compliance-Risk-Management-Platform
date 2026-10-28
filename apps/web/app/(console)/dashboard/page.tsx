"use client";

import type { DashboardSummary, Metric } from "@ngsirs/contracts";
import { MetricCard, StateMessage, StatusBadge, withheldReason } from "@ngsirs/design";
import { useState } from "react";
import { AsyncBlock, Field, Hash, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAsync, useReference } from "@/lib/hooks";
import { fmtDate, fmtDateTime, fmtInt, fmtPct, humanize } from "@/lib/format";

const ARREARS_KEYS = new Set(["confirmed_arrears", "arrears_under_hold"]);

export default function DashboardPage() {
  return (
    <RequirePermission permission="dashboard:read" what="the Compliance Overview">
      <Dashboard />
    </RequirePermission>
  );
}

function Dashboard() {
  const [period, setPeriod] = useState("");
  const [lga, setLga] = useState("");
  const ref = useReference();
  const summary = useAsync(
    () =>
      unwrap<DashboardSummary>(
        api.GET("/api/v1/dashboard/summary", {
          params: { query: { period: period || undefined, lga: lga || undefined, tax_type: "PAYE" } },
        }),
      ),
    [period, lga],
  );
  // The trend always lists every due period in the run, independent of the period filter.
  const periods = summary.data?.trend.map((t) => t.period) ?? [];

  return (
    <>
      <PageHeader
        eyebrow="PAYE · Niger State"
        title="NGSIRS Compliance Overview"
        description="Strategic compliance indicators with their numerators, denominators, time windows and data completeness. Rates are withheld, not estimated, when coverage is too low."
      />
      <form className="filters panel" aria-label="Dashboard filters" onSubmit={(e) => e.preventDefault()}>
        <Field label="Tax period" htmlFor="f-period" hint="Defaults to the latest period whose due date has passed.">
          <select id="f-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">Latest due period</option>
            {[...periods].reverse().map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
        <Field label="LGA" htmlFor="f-lga">
          <select id="f-lga" value={lga} onChange={(e) => setLga(e.target.value)}>
            <option value="">All 25 LGAs</option>
            {ref?.lgas.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name} ({l.code})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tax category" htmlFor="f-tax" hint="PAYE is the only workstream in the MVP.">
          <select id="f-tax" value="PAYE" disabled>
            <option value="PAYE">PAYE (employer)</option>
          </select>
        </Field>
        <p className="m0 small muted" aria-live="polite">
          {summary.loading ? "Updating…" : summary.data ? `Showing ${summary.data.filters.period ?? "—"}${summary.data.filters.lga ? ` · ${summary.data.filters.lga}` : " · all LGAs"}` : ""}
        </p>
      </form>
      <AsyncBlock state={summary} what="the compliance overview">
        {(d) => <DashboardBody d={d} />}
      </AsyncBlock>
    </>
  );
}

function DashboardBody({ d }: { d: DashboardSummary }) {
  if (!d.run) {
    return (
      <StateMessage state="no_data" title="No operational evaluation run yet">
        Indicators appear after the first approved rule set has been evaluated against an imported snapshot.
      </StateMessage>
    );
  }
  const kpis = d.metrics.filter((m) => !ARREARS_KEYS.has(m.key));
  const arrears = d.metrics.filter((m) => ARREARS_KEYS.has(m.key));
  const countWindow = `Current open state at ${fmtDateTime(d.generated_at)}; findings from run as at ${fmtDate(d.run.as_of)}`;
  return (
    <>
      <StateMessage state="info" title="Method and provenance" live="off">
        <p className="m0">{d.method_note}</p>
        <p className="m0 small muted">
          Evaluation run as at {fmtDateTime(d.run.as_of)} covering {d.run.periods[0]} to {d.run.periods[1]} · rule set{" "}
          <Hash value={d.run.rule_set_hash} /> · generated {fmtDateTime(d.generated_at)}
        </p>
      </StateMessage>

      <Section title="Key indicators">
        <div className="grid-3">
          {kpis.map((m) => (
            <MetricCard key={m.key} metric={m} />
          ))}
        </div>
      </Section>

      <Section
        title="Confirmed assessed arrears"
        description="Only served assessments with an outstanding balance. Estimates, unreconciled remittance gaps and risk-indicator amounts are never shown as arrears."
      >
        <div className="grid-2">
          {arrears.map((m) => (
            <MetricCard key={m.key} metric={m} />
          ))}
        </div>
        <p className="m0 small muted">No estimated liability is computed or displayed anywhere on this platform.</p>
      </Section>

      <div className="grid-2">
        <Section title="Trend by tax period" description="On-time filing and remittance per period (all due periods in the run).">
          <TrendTable trend={d.trend} />
        </Section>
        <Section title="On-time filing by LGA" description={`Tax period ${d.filters.period ?? "—"}. LGAs with no obligated employers are omitted.`}>
          <LgaTable rows={d.by_lga} />
        </Section>
      </div>

      <div className="grid-2">
        <Section title="Open findings" description={<CountNote window={countWindow} />}>
          <p className="m0">
            <strong className="big-number">{fmtInt(d.findings.open)}</strong> open findings · Data holds{" "}
            <strong>{fmtInt(d.findings.data_holds)}</strong> · Legal holds <strong>{fmtInt(d.findings.legal_holds)}</strong> · Disputed{" "}
            <strong>{fmtInt(d.findings.disputed)}</strong>
          </p>
          <CountBars title="By signal class" counts={d.findings.by_class} total={d.findings.open} />
          <CountBars title="By priority band" counts={d.findings.by_band} total={d.findings.open} />
          <CountBars title="By rule" counts={d.findings.by_rule} total={d.findings.open} />
          <p className="m0 small muted">
            &ldquo;Unscored&rdquo; findings have unknown exposure (no defensible consequence estimate); they are not low risk.
          </p>
        </Section>
        <div className="stack">
          <Section title="Cases by stage" description={<CountNote window={`All cases at ${fmtDateTime(d.generated_at)}`} />}>
            <CountBars title="Stage" counts={d.cases.by_stage} />
            <p className="m0 small">
              Overdue against SLA: <strong>{fmtInt(d.cases.overdue)}</strong> · Cleared for approved outward contact:{" "}
              <strong>{fmtInt(d.cases.outward_permitted)}</strong>
            </p>
          </Section>
          <Section title="Data quality" description={<CountNote window={`Unresolved items at ${fmtDateTime(d.generated_at)}`} />}>
            <p className="m0 small">
              Quarantined records unresolved: <strong>{fmtInt(d.data_quality.quarantined_unresolved)}</strong> · Identity matches
              pending review: <strong>{fmtInt(d.data_quality.identity_matches_pending)}</strong>
            </p>
          </Section>
        </div>
      </div>

      <Section title="Source freshness" description="Latest extract per source feed against its freshness SLA. Stale sources place affected findings on data hold.">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
          <table className="data">
            <caption className="ng-visually-hidden">Source freshness by feed</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Feed</th>
                <th scope="col">Last extracted</th>
                <th scope="col" className="num">Age (days)</th>
                <th scope="col" className="num">SLA (days)</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {(d.data_quality.sources ?? []).map((s) => (
                <tr key={`${s.source}-${s.feed_type}`}>
                  <th scope="row">{s.source}</th>
                  <td>{s.feed_type}</td>
                  <td>{s.last_extracted_at ? fmtDateTime(s.last_extracted_at) : "Never received"}</td>
                  <td className="num">{s.age_days ?? "—"}</td>
                  <td className="num">{s.sla_days ?? "—"}</td>
                  <td>{s.stale ? <StatusBadge status="stale">Stale</StatusBadge> : <StatusBadge tone="success">Fresh</StatusBadge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}

function CountNote({ window }: { window: string }) {
  return (
    <>
      Counts, not rates (no denominator applies). Time window: {window}. Completeness: as recorded in the latest run.
    </>
  );
}

function RateCell({ m }: { m: Metric }) {
  if (m.value === null) {
    return (
      <span>
        <strong>Withheld</strong> <span className="small muted">— {withheldReason(m)}</span>
      </span>
    );
  }
  return <strong>{fmtPct(m.value)}</strong>;
}

function TrendTable({ trend }: { trend: DashboardSummary["trend"] }) {
  if (trend.length === 0) return <StateMessage state="no_data">No due periods in the evaluation window.</StateMessage>;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
      <table className="data">
        <caption className="ng-visually-hidden">On-time filing and remittance by tax period</caption>
        <thead>
          <tr>
            <th scope="col">Period</th>
            <th scope="col">Filing on time</th>
            <th scope="col" className="num">Num / Den</th>
            <th scope="col">Remittance on time</th>
            <th scope="col" className="num">Num / Den</th>
            <th scope="col" className="num">Completeness (F / R)</th>
          </tr>
        </thead>
        <tbody>
          {trend.map((t) => (
            <tr key={t.period}>
              <th scope="row">{t.period}</th>
              <td>
                <RateCell m={t.filing} />
              </td>
              <td className="num">
                {fmtInt(t.filing.numerator)} / {fmtInt(t.filing.denominator)}
              </td>
              <td>
                <RateCell m={t.remittance} />
              </td>
              <td className="num">
                {fmtInt(t.remittance.numerator)} / {fmtInt(t.remittance.denominator)}
              </td>
              <td className="num">
                {fmtPct(t.filing.completeness, 0)} / {fmtPct(t.remittance.completeness, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LgaTable({ rows }: { rows: DashboardSummary["by_lga"] }) {
  if (rows.length === 0) return <StateMessage state="no_data">No LGA has obligated employers for this period.</StateMessage>;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
      <table className="data">
        <caption className="ng-visually-hidden">On-time filing rate by LGA</caption>
        <thead>
          <tr>
            <th scope="col">LGA</th>
            <th scope="col">Filing on time</th>
            <th scope="col" className="num">Num / Den</th>
            <th scope="col" className="num">Completeness</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.lga}>
              <th scope="row">
                {r.name} <span className="muted small">({r.lga})</span>
              </th>
              <td>
                <RateCell m={r.filing} />
              </td>
              <td className="num">
                {fmtInt(r.filing.numerator)} / {fmtInt(r.filing.denominator)}
              </td>
              <td className="num">{fmtPct(r.filing.completeness, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CountBars({ title, counts, total }: { title: string; counts?: Record<string, number>; total?: number }) {
  const entries = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <p className="m0 small muted">{title}: none.</p>;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="stack-sm">
      <h3 className="small">{title}</h3>
      <ul className="bars">
        {entries.map(([k, v]) => (
          <li key={k}>
            <span>{humanize(k)}</span>
            <span className="bar" aria-hidden="true">
              <span style={{ width: `${(v / max) * 100}%` }} />
            </span>
            <span className="num">
              {fmtInt(v)}
              {total ? <span className="muted small"> ({fmtPct(v / total, 0)})</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
