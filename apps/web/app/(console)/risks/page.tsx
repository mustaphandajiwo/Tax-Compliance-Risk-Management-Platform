"use client";

import type { FindingPage } from "@ngsirs/contracts";
import { RISK_LABEL, RiskIndicator, StatusBadge, consequenceText } from "@ngsirs/design";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { AsyncBlock, Field, PageHeader, Pager, RequirePermission } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { BANDS, FINDING_STATES, HOLD_FILTERS, SIGNAL_CLASSES } from "@/lib/constants";
import { useAsync, useReference } from "@/lib/hooks";
import { fmtConfidence, humanize } from "@/lib/format";

interface Filters {
  q: string;
  lga: string;
  status: string;
  rule: string;
  signal_class: string;
  band: string;
  period: string;
  hold: string;
}

const EMPTY: Filters = { q: "", lga: "", status: "", rule: "", signal_class: "", band: "", period: "", hold: "" };
const PAGE_SIZE = 50;

export default function RisksPage() {
  return (
    <RequirePermission permission="risks:read" what="the Risk Register">
      <RiskRegister />
    </RequirePermission>
  );
}

function RiskRegister() {
  const ref = useReference();
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);

  const list = useAsync(
    () =>
      unwrap<FindingPage>(
        api.GET("/api/v1/risks", {
          params: {
            query: {
              tax_type: "PAYE",
              q: filters.q || undefined,
              lga: filters.lga || undefined,
              status: filters.status || undefined,
              open_only: filters.status ? undefined : true,
              rule: filters.rule.trim().toUpperCase() || undefined,
              signal_class: filters.signal_class || undefined,
              band: filters.band || undefined,
              period: filters.period || undefined,
              hold: (filters.hold || undefined) as "data_hold" | "legal_hold" | "disputed" | "none" | undefined,
              page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    [filters, page],
  );

  function apply(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setFilters(draft);
  }

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <>
      <PageHeader
        eyebrow="PAYE"
        title="Risk Register"
        description={
          <>
            Findings produced by approved, versioned rules. Priority (4 × likelihood × consequence) orders the queue only;
            confidence is shown separately and never merged into it. <span className="label-callout">{RISK_LABEL}</span>
          </>
        }
      />
      <form className="filters panel" onSubmit={apply} aria-label="Risk register filters">
        <Field label="Search" htmlFor="r-q" hint="Finding ref, subject or employer ref">
          <input id="r-q" type="search" value={draft.q} onChange={set("q")} />
        </Field>
        <Field label="Tax type" htmlFor="r-tax">
          <select id="r-tax" value="PAYE" disabled>
            <option>PAYE</option>
          </select>
        </Field>
        <Field label="LGA" htmlFor="r-lga">
          <select id="r-lga" value={draft.lga} onChange={set("lga")}>
            <option value="">All</option>
            {ref?.lgas.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="State" htmlFor="r-status">
          <select id="r-status" value={draft.status} onChange={set("status")}>
            <option value="">Open states</option>
            {FINDING_STATES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Rule ID" htmlFor="r-rule" hint="e.g. FIL-001; comma-separate several">
          <input id="r-rule" type="text" value={draft.rule} onChange={set("rule")} size={10} />
        </Field>
        <Field label="Signal class" htmlFor="r-class">
          <select id="r-class" value={draft.signal_class} onChange={set("signal_class")}>
            <option value="">All</option>
            {SIGNAL_CLASSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority band" htmlFor="r-band">
          <select id="r-band" value={draft.band} onChange={set("band")}>
            <option value="">All</option>
            {BANDS.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tax period" htmlFor="r-period" hint="YYYY-MM">
          <input id="r-period" type="text" pattern="\d{4}-\d{2}" value={draft.period} onChange={set("period")} size={8} />
        </Field>
        <Field label="Holds" htmlFor="r-hold">
          <select id="r-hold" value={draft.hold} onChange={set("hold")}>
            <option value="">Any</option>
            {HOLD_FILTERS.map((h) => (
              <option key={h.value} value={h.value}>
                {h.label}
              </option>
            ))}
          </select>
        </Field>
        <div className="row">
          <button type="submit" className="btn btn-primary">
            Apply filters
          </button>
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => {
              setDraft(EMPTY);
              setFilters(EMPTY);
              setPage(1);
            }}
          >
            Reset
          </button>
        </div>
      </form>

      <AsyncBlock state={list} what="findings" empty={(d) => d.items.length === 0}>
        {(d) => (
          <>
            <p className="m0 small" aria-live="polite" data-testid="denominator-note">
              {d.denominator_note}
            </p>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data" data-testid="risk-table">
                <caption>
                  Findings, page {d.page} — {RISK_LABEL}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Rule ID</th>
                    <th scope="col">Finding</th>
                    <th scope="col">Subject / employer</th>
                    <th scope="col">LGA</th>
                    <th scope="col">Period</th>
                    <th scope="col" className="num">
                      Likelihood
                    </th>
                    <th scope="col" className="num">
                      Consequence
                    </th>
                    <th scope="col" className="num">
                      Confidence
                    </th>
                    <th scope="col">Priority index</th>
                    <th scope="col">Holds</th>
                    <th scope="col">State</th>
                    <th scope="col">Treatment / case</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((f) => (
                    <tr key={f.finding_id}>
                      <td className="nowrap">
                        <code>{f.rule.id}</code>
                        <span className="muted small"> v{f.rule.version}</span>
                      </td>
                      <th scope="row">
                        <Link href={`/risks/${f.finding_id}`}>{f.finding_ref}</Link>
                        <div className="small muted" style={{ fontWeight: 400 }}>
                          {f.title}
                        </div>
                      </th>
                      <td>
                        {f.subject.employer_ref ? (
                          <Link href={`/taxpayers/${encodeURIComponent(f.subject.employer_ref)}`}>{f.employer_name ?? f.subject.employer_ref}</Link>
                        ) : (
                          <code>{f.subject.id}</code>
                        )}
                        {f.employer_name && <div className="small muted">{f.subject.employer_ref}</div>}
                      </td>
                      <td>{f.lga ?? "—"}</td>
                      <td className="nowrap">{f.tax_period ?? "—"}</td>
                      <td className="num">{f.indicators.likelihood ?? "—"}</td>
                      <td className="num">{consequenceText(f.indicators.consequence, f.priority_note)}</td>
                      <td className="num">{fmtConfidence(f.indicators.confidence)}</td>
                      <td>
                        <RiskIndicator
                          priority={f.priority_score}
                          band={f.priority_band}
                          note={f.priority_note}
                          confidence={f.indicators.confidence}
                          showConfidence={false}
                        />
                      </td>
                      <td>
                        {f.holds.length === 0 && !f.flags.data_hold && !f.flags.legal_hold && !f.flags.disputed ? (
                          <span className="muted">None</span>
                        ) : (
                          <div className="stack-sm">
                            {f.flags.data_hold && <StatusBadge status="data_hold" />}
                            {f.flags.legal_hold && <StatusBadge status="legal_hold" />}
                            {f.flags.disputed && <StatusBadge status="disputed" />}
                            {f.holds
                              .filter((h) => !["data_hold", "legal_hold", "disputed"].includes(h))
                              .map((h) => (
                                <StatusBadge key={h} status={h} tone="warning" />
                              ))}
                          </div>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={f.status} />
                      </td>
                      <td>
                        <div className="small">{humanize(f.treatment)}</div>
                        {f.case ? (
                          <Link href={`/cases/${f.case.id}`} className="small">
                            {String(f.case.ref)} · {humanize(String(f.case.stage))}
                          </Link>
                        ) : (
                          <span className="small muted">No case</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          </>
        )}
      </AsyncBlock>
    </>
  );
}
