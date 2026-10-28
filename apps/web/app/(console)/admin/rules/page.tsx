"use client";

import type { EvaluationRunOut, RuleDetail, RuleListItem, RuleLanguage, RunReproduceResult } from "@ngsirs/contracts";
import { StateMessage, StatusBadge } from "@ngsirs/design";
import { useState } from "react";
import { RuleDetailPanel } from "./RuleDetailPanel";
import { Tabs } from "@/components/Tabs";
import { AsyncBlock, ErrorNotice, Field, Hash, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

const CATALOGUE_NOTES: Record<string, string> = {
  pilot: "Pilot rule, implemented and versioned",
  proposed_r1: "Proposed for release 1; not implemented",
  implemented_as_gate: "Implemented as a data-quality gate, not a standalone rule",
  retired_merged: "Retired; merged into another rule",
};

export default function RulesPage() {
  return (
    <RequirePermission permission="rules:read" what="Rule Configuration">
      <RulesAdmin />
    </RequirePermission>
  );
}

function RulesAdmin() {
  const { can } = useAuth();
  const [tab, setTab] = useState("rules");
  const tabs = [
    { id: "rules", label: "Rules" },
    ...(can("evaluations:read") ? [{ id: "runs", label: "Evaluation runs" }] : []),
    { id: "language", label: "Rule language reference" },
  ];
  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Rule Configuration"
        description="Rule studio: draft, validate, backtest, submit, approve (maker-checker, two roles), activate and roll back versioned rules. Every approval is signed and every change is audited."
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} label="Rule configuration sections">
        {tab === "rules" && <RuleCatalogue />}
        {tab === "runs" && <Runs />}
        {tab === "language" && <Language />}
      </Tabs>
    </>
  );
}

function RuleCatalogue() {
  const rules = useAsync(() => unwrap<RuleListItem[]>(api.GET("/api/v1/rules")), []);
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useAsync(
    () => unwrap<RuleDetail>(api.GET("/api/v1/rules/{rule_code}", { params: { path: { rule_code: selected! } } })),
    [selected],
    !!selected,
  );
  return (
    <>
      {selected && (
        <AsyncBlock state={detail} what={`rule ${selected}`}>
          {(d) => (
            <RuleDetailPanel
              rule={d}
              onChanged={() => {
                void detail.reload();
                void rules.reload();
              }}
              onClose={() => setSelected(null)}
            />
          )}
        </AsyncBlock>
      )}
      <Section title="Rule catalogue">
        <Field label="Catalogue status" htmlFor="rc-status">
          <select id="rc-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {Object.keys(CATALOGUE_NOTES).map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <AsyncBlock state={rules} what="rules" empty={(d) => d.length === 0}>
          {(d) => (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption className="ng-visually-hidden">Rule catalogue</caption>
                <thead>
                  <tr>
                    <th scope="col">Rule</th>
                    <th scope="col">Title</th>
                    <th scope="col">Domain</th>
                    <th scope="col">Catalogue status</th>
                    <th scope="col">Active version</th>
                    <th scope="col">Versions</th>
                    <th scope="col">Default treatment</th>
                    <th scope="col">
                      <span className="ng-visually-hidden">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d
                    .filter((r) => !status || r.catalogue_status === status)
                    .map((r) => (
                      <tr key={r.rule_code}>
                        <th scope="row">
                          <code>{r.rule_code}</code>
                          {r.legacy_codes.length > 0 && <div className="small muted">{r.legacy_codes.join(", ")}</div>}
                        </th>
                        <td>{r.title}</td>
                        <td>{humanize(r.domain)}</td>
                        <td>
                          <StatusBadge tone={r.catalogue_status === "pilot" ? "success" : r.catalogue_status === "retired_merged" ? "neutral" : "info"} title={CATALOGUE_NOTES[r.catalogue_status]}>
                            {humanize(r.catalogue_status)}
                          </StatusBadge>
                        </td>
                        <td>
                          {r.active_version ?? <span className="muted">None</span>}
                          {r.active_since && <div className="small muted">since {fmtDateTime(r.active_since)}</div>}
                        </td>
                        <td className="small">{r.versions.map((v) => `${v.version} (${humanize(v.status)})`).join(", ") || "—"}</td>
                        <td className="small">{humanize(r.default_treatment)}</td>
                        <td>
                          <button type="button" className="btn btn-sm" onClick={() => setSelected(r.rule_code)} aria-label={`Open rule ${r.rule_code}`}>
                            Open
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </Section>
    </>
  );
}

function Runs() {
  const runs = useAsync(() => unwrap<EvaluationRunOut[]>(api.GET("/api/v1/rules/evaluations")), []);
  return (
    <Section title="Evaluation runs" description="Each run evaluates an approved rule set against an immutable input snapshot. Reproducing a run re-evaluates it and compares the outcome digest.">
      <AsyncBlock state={runs} what="evaluation runs" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Evaluation runs</caption>
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Mode · status</th>
                  <th scope="col">As at · periods</th>
                  <th scope="col">Rule set / snapshot</th>
                  <th scope="col" className="num">Findings</th>
                  <th scope="col">Triggered by</th>
                  <th scope="col">Reproduce</th>
                </tr>
              </thead>
              <tbody>
                {d.map((r) => (
                  <RunRow key={r.id} r={r} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncBlock>
    </Section>
  );
}

function RunRow({ r }: { r: EvaluationRunOut }) {
  const m = useMutation(() => unwrap<RunReproduceResult>(api.POST("/api/v1/rules/evaluations/{run_id}/reproduce", { params: { path: { run_id: r.id } } })));
  return (
    <tr>
      <th scope="row">
        <Hash value={r.id} len={8} />
        <div className="small muted">{fmtDateTime(r.started_at)}</div>
      </th>
      <td>
        {humanize(r.mode)} · <StatusBadge status={r.status} />
      </td>
      <td className="small">
        {fmtDateTime(r.as_of)}
        <div>
          {r.period_from} – {r.period_to}
        </div>
      </td>
      <td className="small">
        rules <Hash value={r.rule_set_hash} len={10} />
        <div>
          snapshot <Hash value={r.snapshot_hash} len={10} />
        </div>
        <div className="muted">{r.rule_versions.length} rule versions</div>
      </td>
      <td className="num">{String(r.counts.findings ?? "—")}</td>
      <td>{r.triggered_by}</td>
      <td>
        <button type="button" className="btn btn-sm" onClick={() => void m.run()} disabled={m.pending}>
          {m.pending ? "Reproducing…" : "Reproduce run"}
        </button>
        <div aria-live="polite" className="small">
          {m.result && (
            <span>
              {m.result.reproduced ? <StatusBadge tone="success">Reproduced</StatusBadge> : <StatusBadge tone="danger">Differs</StatusBadge>} digest{" "}
              <Hash value={m.result.outcome_digest} len={10} />
            </span>
          )}
        </div>
        <ErrorNotice error={m.error} />
      </td>
    </tr>
  );
}

function Language() {
  const lang = useAsync(() => unwrap<RuleLanguage>(api.GET("/api/v1/rules/language")), []);
  return (
    <AsyncBlock state={lang} what="the rule language reference">
      {(l) => (
        <div className="stack">
          <Section title="Operators and combinators">
            <p className="m0">
              Operators: {l.operators.map((o) => <code key={o}>{o} </code>)}
            </p>
            <p className="m0">
              Combinators: {l.combinators.map((o) => <code key={o}>{o} </code>)}
            </p>
          </Section>
          {Object.entries(l.fact_kinds).map(([kind, fields]) => (
            <Section key={kind} title={`Fact kind: ${kind}`} level={3}>
              <details>
                <summary>{Object.keys(fields).length} fields</summary>
                <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                  <table className="data">
                    <caption className="ng-visually-hidden">Fields of {kind}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Field</th>
                        <th scope="col">Type</th>
                        <th scope="col">Nullable</th>
                        <th scope="col">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(fields).map(([name, f]) => (
                        <tr key={name}>
                          <th scope="row">
                            <code>{name}</code>
                          </th>
                          <td>
                            {f.type}
                            {f.values ? <div className="small muted">{f.values.join(", ")}</div> : null}
                          </td>
                          <td>{f.nullable ? "Yes" : "No"}</td>
                          <td className="small">{f.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </Section>
          ))}
          <div className="grid-3">
            {(["eligibility", "exclusions", "holds"] as const).map((k) => (
              <Section key={k} title={humanize(k)} level={3}>
                <dl className="kv kv--1">
                  {Object.entries(l[k]).map(([name, p]) => (
                    <div key={name} className="kv__item">
                      <dt>
                        <code>{name}</code>
                      </dt>
                      <dd className="small">{p.description}</dd>
                    </div>
                  ))}
                </dl>
              </Section>
            ))}
          </div>
          <Section title="Treatments" level={3}>
            <ul className="m0">
              {Object.entries(l.treatments).map(([k, t]) => (
                <li key={k}>
                  <code>{k}</code> — {t.label} · gate: {t.human_gate} · {t.outward ? "outward (taxpayer contact)" : "internal"}
                </li>
              ))}
            </ul>
          </Section>
          <StateMessage state="info" live="off" title="History series">
            <code className="small">{JSON.stringify(l.history_series)}</code>
          </StateMessage>
        </div>
      )}
    </AsyncBlock>
  );
}
