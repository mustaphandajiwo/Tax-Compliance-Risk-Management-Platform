"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  ActionResult,
  Badge,
  Card,
  Empty,
  ErrorBox,
  JsonBlock,
  Loading,
  NoAccess,
  Notice,
  PageHead,
  ReasonField,
  reasonOk,
  SelectField,
  StatusBadge,
  Tabs,
  TabPanel,
  TextArea,
  TextField,
  useAction,
  useAsync,
} from "@/components/ui";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, dateTime, humanize, pct, PERIOD_RE } from "@/lib/format";
import { DIMENSIONS, TAX_TYPES } from "@/lib/reference";
import type { LegalRuleIn, LegalRuleOut, ModelTestResult, RiskModelOut, RuleTestResult } from "@/lib/types";

type Tab = "legal" | "models";

export default function RulesPage() {
  const { can } = useAuth();
  const tabs: { id: Tab; label: string }[] = [
    ...(can("legal_rules.read") ? [{ id: "legal" as const, label: "Legal catalogue" }] : []),
    ...(can("risk.read") ? [{ id: "models" as const, label: "Risk model studio" }] : []),
  ];
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? "legal");
  if (!tabs.length) return <NoAccess permission="legal_rules.read" />;
  return (
    <>
      <PageHead
        title="Rules & models"
        description="Versioned legal obligations and risk-model configuration. Every change is drafted, tested in a sandbox, and approved by a second person before it takes effect."
      />
      <Tabs<Tab> label="Rules and models" tabs={tabs} value={tab} onChange={setTab} />
      <TabPanel id={tab}>{tab === "legal" ? <LegalCatalogue /> : <ModelStudio />}</TabPanel>
    </>
  );
}

/* =========================================================== legal catalogue */

function LegalCatalogue() {
  const { can } = useAuth();
  const [taxType, setTaxType] = useState("");
  const [status, setStatus] = useState("");
  const res = useAsync(() => apiGet("/v1/legal-rules", { query: { tax_type: taxType, status } }), [taxType, status]);
  const [selected, setSelected] = useState<LegalRuleOut | null>(null);
  const [drafting, setDrafting] = useState<LegalRuleOut | "new" | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const groups = useMemo(() => {
    const m = new Map<string, LegalRuleOut[]>();
    for (const r of res.data ?? []) m.set(r.rule_code, [...(m.get(r.rule_code) ?? []), r]);
    for (const v of m.values()) v.sort((a, b) => b.version - a.version);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [res.data]);

  return (
    <div className="stack">
      <Card
        actions={
          can("legal_rules.draft") ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setDrafting("new")}>
              Draft new rule
            </button>
          ) : undefined
        }
        title="Catalogue"
      >
        <div className="filters">
          <SelectField label="Tax type" value={taxType} onChange={setTaxType} options={[...TAX_TYPES]} allowEmpty emptyLabel="All" />
          <SelectField label="Status" value={status} onChange={setStatus} options={["draft", "pending_approval", "approved", "retired"]} allowEmpty emptyLabel="All" />
        </div>
        <p className="tiny muted" style={{ marginTop: 8 }}>
          Citations marked PLACEHOLDER or ILLUSTRATIVE require sign-off by tax counsel before production use.
        </p>
      </Card>
      {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
      {res.loading && !res.data && <Loading />}
      {drafting && (
        <RuleDraftForm
          base={drafting === "new" ? null : drafting}
          onCancel={() => setDrafting(null)}
          onDone={(r) => {
            setDrafting(null);
            setSelected(r);
            setFlash(`Draft ${r.rule_code} v${r.version} created. Test it in the sandbox, then submit it for approval by a second legal officer.`);
            res.reload();
          }}
        />
      )}
      <ActionResult error={null} success={flash} />
      <div className="split">
        <div className="stack">
          {groups.map(([code, versions]) => (
            <Card key={code} title={<h3 className="mb-0 mono">{code}</h3>} pad={false}>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Version</th>
                      <th scope="col">Title</th>
                      <th scope="col">Valid</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {versions.map((r) => (
                      <tr key={r.id} className={selected?.id === r.id ? "selected" : undefined}>
                        <td>
                          <button type="button" className="row-button" onClick={() => setSelected(r)}>
                            v{r.version}
                          </button>
                        </td>
                        <td className="small">{r.title}</td>
                        <td className="nowrap small">
                          {date(r.valid_from)} → {r.valid_to ? date(r.valid_to) : "open-ended"}
                        </td>
                        <td>
                          <StatusBadge status={r.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ))}
          {res.data && groups.length === 0 && <Empty>No rules match.</Empty>}
        </div>
        {selected ? (
          <RuleDetail
            key={selected.id}
            r={selected}
            onChanged={(r) => {
              setSelected(r);
              res.reload();
            }}
            onDraftFrom={() => setDrafting(selected)}
          />
        ) : (
          <Card title="Rule version">
            <Empty>Select a version to see its definition, test it, or act on it.</Empty>
          </Card>
        )}
      </div>
    </div>
  );
}

function RuleDetail({ r, onChanged, onDraftFrom }: { r: LegalRuleOut; onChanged: (r: LegalRuleOut) => void; onDraftFrom: () => void }) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [period, setPeriod] = useState(r.frequency === "monthly" ? "2026-09" : "2025");
  const act = useAction();
  const test = useAction();
  const [testResult, setTestResult] = useState<RuleTestResult | null>(null);

  const canSubmit = r.status === "draft" && can("legal_rules.draft");
  const canApprove = r.status === "pending_approval" && can("legal_rules.approve");
  const canRetire = r.status === "approved" && can("legal_rules.approve");

  async function decide(kind: "approve" | "retire") {
    if (!reasonOk(reason)) return act.setError("A reason of at least 5 characters is required.");
    const out = await act.run(
      () =>
        kind === "approve"
          ? apiPost("/v1/legal-rules/{rule_id}/approve", { path: { rule_id: r.id }, body: { reason: reason.trim() } })
          : apiPost("/v1/legal-rules/{rule_id}/retire", { path: { rule_id: r.id }, body: { reason: reason.trim() } }),
      (x) => `Version ${x.version} is now ${humanize(x.status).toLowerCase()}.`,
    );
    if (out) {
      setReason("");
      onChanged(out);
    }
  }

  async function runTest(e: FormEvent) {
    e.preventDefault();
    if (!PERIOD_RE.test(period)) return test.setError("Period must be YYYY or YYYY-MM.");
    const out = await test.run(async () => (await apiPost("/v1/legal-rules/{rule_id}/test", { path: { rule_id: r.id }, body: { period } })) as unknown as RuleTestResult);
    if (out) setTestResult(out);
  }

  return (
    <Card title={`${r.rule_code} v${r.version}`} actions={<StatusBadge status={r.status} />}>
      <div className="stack-sm">
        <dl className="kv">
          <dt>Title</dt>
          <dd>{r.title}</dd>
          <dt>Tax type · frequency</dt>
          <dd>
            {r.tax_type} · {humanize(r.frequency)}
          </dd>
          <dt>Validity window</dt>
          <dd>
            {date(r.valid_from)} → {r.valid_to ? date(r.valid_to) : "open-ended"}
          </dd>
          <dt>Citation</dt>
          <dd>
            {r.citation} {/PLACEHOLDER|ILLUSTRATIVE/i.test(r.citation) && <Badge tone="warn">Needs legal sign-off</Badge>}
          </dd>
          <dt>Jurisdiction</dt>
          <dd className="small">{r.jurisdiction}</dd>
          <dt>Deadline</dt>
          <dd>
            <code>{JSON.stringify(r.deadline)}</code>
          </dd>
          <dt>Eligibility</dt>
          <dd>
            <code>{JSON.stringify(r.eligibility ?? {})}</code>
          </dd>
          <dt>Evidence required</dt>
          <dd>{(r.evidence_requirements ?? []).join("; ") || "—"}</dd>
          <dt>Exemptions</dt>
          <dd>{(r.exemptions ?? []).join("; ") || "—"}</dd>
          <dt>Approved</dt>
          <dd>{r.approved_at ? dateTime(r.approved_at) : "—"}</dd>
          {r.notes && (
            <>
              <dt>Notes</dt>
              <dd>{r.notes}</dd>
            </>
          )}
        </dl>

        <form onSubmit={runTest} className="row" aria-label="Test rule in sandbox" style={{ alignItems: "flex-end" }}>
          <TextField label="Sandbox: test period" value={period} onChange={setPeriod} hint="YYYY or YYYY-MM" />
          <button type="submit" className="btn" disabled={test.busy}>
            {test.busy ? "Testing…" : "Test"}
          </button>
        </form>
        <ActionResult error={test.error} success={null} />
        {testResult && (
          <div aria-live="polite">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Due date produced</th>
                  <th scope="col">This version valid?</th>
                  <th scope="col">Version in force</th>
                </tr>
              </thead>
              <tbody>
                {testResult.results.map((x) => (
                  <tr key={x.period}>
                    <td>{x.period}</td>
                    <td>{date(x.due_date)}</td>
                    <td>{x.this_version_valid ? <Badge tone="ok">Yes</Badge> : <Badge tone="warn">No — outside validity window</Badge>}</td>
                    <td>{x.version_in_force !== null ? `v${x.version_in_force}` : "none"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="row" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          {can("legal_rules.draft") && (
            <button type="button" className="btn" onClick={onDraftFrom}>
              Draft new version from this
            </button>
          )}
          {canSubmit && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={act.busy}
              onClick={async () => {
                const out = await act.run(() => apiPost("/v1/legal-rules/{rule_id}/submit", { path: { rule_id: r.id } }), "Submitted for approval by a second legal officer.");
                if (out) onChanged(out);
              }}
            >
              Submit for approval
            </button>
          )}
        </div>
        {(canApprove || canRetire) && (
          <div className="stack-sm">
            <ReasonField value={reason} onChange={setReason} />
            <div className="row">
              {canApprove && (
                <button type="button" className="btn btn-primary" disabled={act.busy || !reasonOk(reason)} onClick={() => decide("approve")}>
                  Approve version
                </button>
              )}
              {canRetire && (
                <button type="button" className="btn btn-danger" disabled={act.busy || !reasonOk(reason)} onClick={() => decide("retire")}>
                  Retire version
                </button>
              )}
            </div>
            {canApprove && <p className="tiny muted mb-0">Second-person rule: the drafter of a version cannot approve it.</p>}
          </div>
        )}
        <ActionResult error={act.error} success={act.success} />
      </div>
    </Card>
  );
}

function RuleDraftForm({ base, onCancel, onDone }: { base: LegalRuleOut | null; onCancel: () => void; onDone: (r: LegalRuleOut) => void }) {
  const { me } = useAuth();
  const [f, setF] = useState({
    rule_code: base?.rule_code ?? "",
    title: base?.title ?? "",
    jurisdiction: base?.jurisdiction ?? me?.tenant.legal_jurisdiction ?? "",
    tax_type: base?.tax_type ?? "PAYE",
    frequency: base?.frequency ?? "monthly",
    eligibility: JSON.stringify(base?.eligibility ?? {}, null, 0),
    deadline: JSON.stringify(base?.deadline ?? { type: "days_after_period_end", days: 10 }, null, 0),
    exemptions: (base?.exemptions ?? []).join("\n"),
    evidence_requirements: (base?.evidence_requirements ?? []).join("\n"),
    citation: base?.citation ?? "",
    valid_from: "",
    valid_to: "",
    notes: "",
  });
  const act = useAction();
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  async function submit(e: FormEvent) {
    e.preventDefault();
    let eligibility: Record<string, unknown>;
    let deadline: Record<string, unknown>;
    try {
      eligibility = JSON.parse(f.eligibility || "{}") as Record<string, unknown>;
      deadline = JSON.parse(f.deadline) as Record<string, unknown>;
    } catch {
      return act.setError("Eligibility and deadline must be valid JSON objects.");
    }
    if (!/^[A-Z0-9_]{3,60}$/.test(f.rule_code)) return act.setError("Rule code must be 3–60 characters: A–Z, 0–9, underscore.");
    if (!f.valid_from) return act.setError("Valid-from date is required.");
    const body: LegalRuleIn = {
      rule_code: f.rule_code,
      title: f.title,
      jurisdiction: f.jurisdiction,
      tax_type: f.tax_type as LegalRuleIn["tax_type"],
      frequency: f.frequency as LegalRuleIn["frequency"],
      eligibility,
      deadline,
      exemptions: f.exemptions.split("\n").map((s) => s.trim()).filter(Boolean),
      evidence_requirements: f.evidence_requirements.split("\n").map((s) => s.trim()).filter(Boolean),
      citation: f.citation,
      valid_from: f.valid_from,
      valid_to: f.valid_to || null,
      notes: f.notes || null,
    };
    const r = await act.run(() => apiPost("/v1/legal-rules", { body }), (x) => `Draft ${x.rule_code} v${x.version} created. Test it, then submit for approval.`);
    if (r) onDone(r);
  }

  return (
    <Card title={base ? `Draft new version of ${base.rule_code}` : "Draft new legal rule"}>
      <form onSubmit={submit} className="stack-sm" aria-label="Draft legal rule">
        <div className="form-grid">
          <TextField label="Rule code" value={f.rule_code} onChange={set("rule_code")} required hint="Same code = new version" />
          <TextField label="Title" value={f.title} onChange={set("title")} required />
          <SelectField label="Tax type" value={f.tax_type} onChange={set("tax_type")} options={[...TAX_TYPES]} />
          <SelectField label="Frequency" value={f.frequency} onChange={set("frequency")} options={["monthly", "annual"]} />
          <TextField label="Valid from" type="date" value={f.valid_from} onChange={set("valid_from")} required />
          <TextField label="Valid to (optional)" type="date" value={f.valid_to} onChange={set("valid_to")} />
          <TextField className="span-2" label="Jurisdiction" value={f.jurisdiction} onChange={set("jurisdiction")} required />
          <TextField className="span-2" label="Citation" value={f.citation} onChange={set("citation")} required hint="Statute and section. Mark unverified citations as PLACEHOLDER." />
          <TextArea label="Deadline (JSON)" value={f.deadline} onChange={set("deadline")} code rows={3} />
          <TextArea label="Eligibility (JSON)" value={f.eligibility} onChange={set("eligibility")} code rows={3} />
          <TextArea label="Exemptions (one per line)" value={f.exemptions} onChange={set("exemptions")} rows={2} />
          <TextArea label="Evidence requirements (one per line)" value={f.evidence_requirements} onChange={set("evidence_requirements")} rows={2} />
          <TextArea className="span-2" label="Notes" value={f.notes} onChange={set("notes")} rows={2} />
        </div>
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy}>
            {act.busy ? "Saving…" : "Save draft"}
          </button>
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
        <ActionResult error={act.error} success={act.success} />
      </form>
    </Card>
  );
}

/* =========================================================== model studio */

function ModelStudio() {
  const { can } = useAuth();
  const models = useAsync(() => apiGet("/v1/risk-models"), []);
  const catalogue = useAsync(async () => (await apiGet("/v1/signal-catalogue")) as { default_weights?: Record<string, number>; default_thresholds?: Record<string, number> }, []);
  const [selected, setSelected] = useState<RiskModelOut | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const approved = models.data?.find((m) => m.status === "approved");

  return (
    <div className="stack">
      <Notice tone="info">
        Weights are policy choices, not validated estimates. Use the sandbox to compare how many taxpayers a draft would flag against the approved model before submitting it for a
        second analyst&apos;s approval.
      </Notice>
      {drafting && (
        <ModelDraftForm
          base={selected ?? approved ?? null}
          defaults={catalogue.data}
          onCancel={() => setDrafting(false)}
          onDone={(m) => {
            setDrafting(false);
            setSelected(m);
            setFlash(`Draft model v${m.version} created. Run the sandbox comparison, then submit it for a second person's approval.`);
            models.reload();
          }}
        />
      )}
      <ActionResult error={null} success={flash} />
      <div className="split">
        <Card
          title="Model versions"
          pad={false}
          actions={
            can("risk_models.draft") ? (
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setDrafting(true)}>
                Draft new version
              </button>
            ) : undefined
          }
        >
          {models.error && <ErrorBox error={models.error} onRetry={models.reload} />}
          {models.loading && !models.data && <Loading />}
          {models.data && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Version</th>
                    <th scope="col">Name</th>
                    <th scope="col">Weights</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[...models.data]
                    .sort((a, b) => b.version - a.version)
                    .map((m) => (
                      <tr key={m.id} className={selected?.id === m.id ? "selected" : undefined}>
                        <td>
                          <button type="button" className="row-button" onClick={() => setSelected(m)}>
                            v{m.version}
                          </button>
                        </td>
                        <td className="small">{m.name}</td>
                        <td className="tiny nowrap">
                          {DIMENSIONS.map((d) => (
                            <div key={d}>
                              {humanize(d)} {pct(m.weights[d] ?? null, 0)}
                            </div>
                          ))}
                        </td>
                        <td>
                          <StatusBadge status={m.status} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {selected ? (
          <ModelDetail
            key={selected.id}
            m={selected}
            onChanged={(m) => {
              setSelected(m);
              models.reload();
            }}
          />
        ) : (
          <Card title="Model version">
            <Empty>Select a version to inspect, test or approve it.</Empty>
          </Card>
        )}
      </div>
      <RiskRuns />
    </div>
  );
}

function ModelDetail({ m, onChanged }: { m: RiskModelOut; onChanged: (m: RiskModelOut) => void }) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [taxType, setTaxType] = useState("PAYE");
  const [period, setPeriod] = useState("2026");
  const act = useAction();
  const test = useAction();
  const [result, setResult] = useState<ModelTestResult | null>(null);

  const canSubmit = m.status === "draft" && can("risk_models.draft");
  const canApprove = m.status === "pending_approval" && can("risk_models.approve");
  const canReinstate = m.status === "retired" && !!m.approved_by && can("risk_models.approve");

  async function decide(kind: "approve" | "reinstate") {
    if (!reasonOk(reason)) return act.setError("A reason of at least 5 characters is required.");
    const out = await act.run(
      () =>
        kind === "approve"
          ? apiPost("/v1/risk-models/{model_id}/approve", { path: { model_id: m.id }, body: { reason: reason.trim() } })
          : apiPost("/v1/risk-models/{model_id}/reinstate", { path: { model_id: m.id }, body: { reason: reason.trim() } }),
      (x) => `Model v${x.version} is now ${humanize(x.status).toLowerCase()}.`,
    );
    if (out) {
      setReason("");
      onChanged(out);
    }
  }

  async function runTest(e: FormEvent) {
    e.preventDefault();
    if (period && !PERIOD_RE.test(period)) return test.setError("Period must be YYYY or YYYY-MM.");
    const out = await test.run(async () => (await apiPost("/v1/risk-models/{model_id}/test", { path: { model_id: m.id }, query: { tax_type: taxType, period } })) as unknown as ModelTestResult);
    if (out) setResult(out);
  }

  return (
    <Card title={`Model v${m.version} — ${m.name}`} actions={<StatusBadge status={m.status} />}>
      <div className="stack-sm">
        <div className="grid-2">
          <div>
            <h3>Weights</h3>
            <table className="data">
              <tbody>
                {Object.entries(m.weights).map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row" style={{ position: "static" }}>
                      {humanize(k)}
                    </th>
                    <td className="num">{pct(v, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <h3>Thresholds</h3>
            <table className="data">
              <tbody>
                {Object.entries(m.thresholds).map(([k, v]) => (
                  <tr key={k}>
                    <th scope="row" style={{ position: "static" }}>
                      {humanize(k)}
                    </th>
                    <td className="num">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {m.notes && <p className="small muted mb-0">{m.notes}</p>}
        <p className="tiny muted mb-0">
          Created {dateTime(m.created_at)} · approved {m.approved_at ? dateTime(m.approved_at) : "—"}
        </p>

        {can("risk_models.draft") && (
          <form onSubmit={runTest} className="row" aria-label="Sandbox comparison" style={{ alignItems: "flex-end", borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <SelectField label="Sandbox tax type" value={taxType} onChange={setTaxType} options={[...TAX_TYPES]} />
            <TextField label="Period" value={period} onChange={setPeriod} hint="YYYY or YYYY-MM" />
            <button type="submit" className="btn" disabled={test.busy}>
              {test.busy ? "Comparing…" : "Run sandbox comparison"}
            </button>
          </form>
        )}
        <ActionResult error={test.error} success={null} />
        {result && (
          <div aria-live="polite">
            <table className="data">
              <caption>Sandbox comparison (nothing persisted)</caption>
              <tbody>
                <tr>
                  <th scope="row">Sample size</th>
                  <td className="num">{result.sample_size}</td>
                </tr>
                <tr>
                  <th scope="row">Flagged by this model (v{result.model_version})</th>
                  <td className="num">{result.flagged_candidate}</td>
                </tr>
                <tr>
                  <th scope="row">Flagged by approved model{result.compared_to ? ` (v${result.compared_to})` : ""}</th>
                  <td className="num">{result.flagged_current}</td>
                </tr>
                <tr>
                  <th scope="row">Taxpayers whose flag would change</th>
                  <td className="num">
                    <strong>{result.changed_flags}</strong>
                  </td>
                </tr>
              </tbody>
            </table>
            <JsonBlock value={result} summary="Full sandbox output" />
          </div>
        )}

        {canSubmit && (
          <div className="row">
            <button
              type="button"
              className="btn btn-primary"
              disabled={act.busy}
              onClick={async () => {
                const out = await act.run(() => apiPost("/v1/risk-models/{model_id}/submit", { path: { model_id: m.id } }), "Submitted for approval by a second person.");
                if (out) onChanged(out);
              }}
            >
              Submit for approval
            </button>
          </div>
        )}
        {(canApprove || canReinstate) && (
          <div className="stack-sm">
            <ReasonField value={reason} onChange={setReason} />
            <div className="row">
              {canApprove && (
                <button type="button" className="btn btn-primary" disabled={act.busy || !reasonOk(reason)} onClick={() => decide("approve")}>
                  Approve model (retires current)
                </button>
              )}
              {canReinstate && (
                <button type="button" className="btn" disabled={act.busy || !reasonOk(reason)} onClick={() => decide("reinstate")}>
                  Reinstate this version (rollback)
                </button>
              )}
            </div>
          </div>
        )}
        <ActionResult error={act.error} success={act.success} />
      </div>
    </Card>
  );
}

function ModelDraftForm({
  base,
  defaults,
  onCancel,
  onDone,
}: {
  base: RiskModelOut | null;
  defaults?: { default_weights?: Record<string, number>; default_thresholds?: Record<string, number> };
  onCancel: () => void;
  onDone: (m: RiskModelOut) => void;
}) {
  const initialW = base?.weights ?? defaults?.default_weights ?? { registration: 0.15, filing: 0.25, reporting: 0.35, payment: 0.25 };
  const initialT = base?.thresholds ?? defaults?.default_thresholds ?? {};
  const [name, setName] = useState(base ? `${base.name} (revised)` : "");
  const [weights, setWeights] = useState<Record<string, string>>(Object.fromEntries(DIMENSIONS.map((d) => [d, String(initialW[d] ?? 0)])));
  const [thresholds, setThresholds] = useState<Record<string, string>>(Object.fromEntries(Object.entries(initialT).map(([k, v]) => [k, String(v)])));
  const [notes, setNotes] = useState("");
  const act = useAction();
  const sum = DIMENSIONS.reduce((a, d) => a + (Number(weights[d]) || 0), 0);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const w = Object.fromEntries(DIMENSIONS.map((d) => [d, Number(weights[d])]));
    if (Object.values(w).some((x) => !Number.isFinite(x) || x < 0)) return act.setError("Weights must be non-negative numbers.");
    if (Math.abs(sum - 1) > 0.001) return act.setError(`Weights must sum to 1 (currently ${sum.toFixed(3)}).`);
    const t = Object.fromEntries(Object.entries(thresholds).map(([k, v]) => [k, Number(v)]));
    if (Object.values(t).some((x) => !Number.isFinite(x))) return act.setError("Thresholds must be numbers.");
    const r = await act.run(() => apiPost("/v1/risk-models", { body: { name: name.trim(), weights: w, thresholds: t, notes: notes || null } }), (m) => `Draft model v${m.version} created.`);
    if (r) onDone(r);
  }

  return (
    <Card title={base ? `Draft new model version (from v${base.version})` : "Draft new model version"}>
      <form onSubmit={submit} className="stack-sm" aria-label="Draft risk model">
        <TextField label="Name" value={name} onChange={setName} required />
        <fieldset>
          <legend>Dimension weights (must sum to 1 — currently {sum.toFixed(3)})</legend>
          <div className="filters">
            {DIMENSIONS.map((d) => (
              <TextField key={d} label={humanize(d)} type="number" value={weights[d] ?? ""} onChange={(v) => setWeights({ ...weights, [d]: v })} inputMode="decimal" />
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Thresholds</legend>
          <div className="filters">
            {Object.keys(thresholds).map((k) => (
              <TextField key={k} label={humanize(k)} type="number" value={thresholds[k] ?? ""} onChange={(v) => setThresholds({ ...thresholds, [k]: v })} inputMode="decimal" />
            ))}
          </div>
        </fieldset>
        <TextArea label="Notes / rationale" value={notes} onChange={setNotes} rows={2} />
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy}>
            {act.busy ? "Saving…" : "Save draft"}
          </button>
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
        <ActionResult error={act.error} success={act.success} />
      </form>
    </Card>
  );
}

function RiskRuns() {
  const { can } = useAuth();
  const runs = useAsync(() => apiGet("/v1/risk-runs", { query: { limit: 20 } }), []);
  const [taxType, setTaxType] = useState<"PAYE" | "DA">("PAYE");
  const [period, setPeriod] = useState("2026");
  const act = useAction();

  async function trigger(e: FormEvent) {
    e.preventDefault();
    if (!PERIOD_RE.test(period)) return act.setError("Period must be YYYY or YYYY-MM.");
    const r = await act.run(
      () => apiPost("/v1/risk-runs", { body: { tax_type: taxType, period } }),
      (x) => `Run ${x.id.slice(0, 8)} ${humanize(x.status).toLowerCase()}: ${x.assessed} assessed, ${x.alerts_created} alerts, ${x.suppressed} suppressed (low confidence).`,
    );
    if (r) runs.reload();
  }

  return (
    <Card title="Risk runs" pad={false}>
      {can("risk_runs.create") && (
        <div className="card-body">
          <form onSubmit={trigger} className="row" aria-label="Trigger risk run" style={{ alignItems: "flex-end" }}>
            <SelectField label="Tax type" value={taxType} onChange={(v) => setTaxType(v as "PAYE" | "DA")} options={[...TAX_TYPES]} />
            <TextField label="Period" value={period} onChange={setPeriod} hint="YYYY or YYYY-MM" />
            <button type="submit" className="btn btn-primary" disabled={act.busy}>
              {act.busy ? "Running…" : "Trigger risk run"}
            </button>
            <span className="tiny muted">Uses the approved model. New assessments supersede older ones for the same period.</span>
          </form>
          <div style={{ marginTop: 8 }}>
            <ActionResult error={act.error} success={act.success} />
          </div>
        </div>
      )}
      {runs.error && <ErrorBox error={runs.error} onRetry={runs.reload} />}
      {runs.loading && !runs.data && <Loading />}
      {runs.data && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Created</th>
                <th scope="col">Tax · period</th>
                <th scope="col">As of</th>
                <th scope="col">Model · engine</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Assessed
                </th>
                <th scope="col" className="num">
                  Alerts
                </th>
                <th scope="col" className="num">
                  Suppressed
                </th>
                <th scope="col">Dataset hash</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.items.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{dateTime(r.created_at)}</td>
                  <td>
                    {r.tax_type} · {r.period}
                  </td>
                  <td>{date(r.as_of)}</td>
                  <td className="small">
                    v{r.model_version} · {r.engine_version}
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                    {r.error && <div className="tiny" style={{ color: "var(--danger)" }}>{r.error}</div>}
                  </td>
                  <td className="num">{r.assessed}</td>
                  <td className="num">{r.alerts_created}</td>
                  <td className="num">{r.suppressed}</td>
                  <td className="tiny">
                    <span className="hash" title={r.dataset_hash ?? ""}>
                      {r.dataset_hash ? `${r.dataset_hash.slice(0, 12)}…` : "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
