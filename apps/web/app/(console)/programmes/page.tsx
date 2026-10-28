"use client";

import type { Programme, ProgrammeEvaluation } from "@ngsirs/contracts";
import { MetricCard, StateMessage, StatusBadge } from "@ngsirs/design";
import { useState, type FormEvent } from "react";
import { AsyncBlock, ErrorNotice, Field, KeyValues, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation, useReference } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

export default function ProgrammesPage() {
  return (
    <RequirePermission permission="programmes:read" what="Compliance Programmes">
      <Programmes />
    </RequirePermission>
  );
}

function Programmes() {
  const { can } = useAuth();
  const list = useAsync(() => unwrap<Programme[]>(api.GET("/api/v1/programmes")), []);
  return (
    <>
      <PageHeader
        eyebrow="PAYE interventions"
        title="Compliance Programmes"
        description="Cohort interventions with a defined population, denominator, baseline and evaluation window. Effects are reported as intervention vs comparison change (difference-in-differences) with their denominators and caveats."
      />
      {can("programmes:manage") && <CreateProgramme onCreated={() => void list.reload()} />}
      <AsyncBlock state={list} what="programmes" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="stack">
            {d.map((p) => (
              <ProgrammeCard key={p.id} p={p} onChanged={() => void list.reload()} />
            ))}
          </div>
        )}
      </AsyncBlock>
    </>
  );
}

function ProgrammeCard({ p, onChanged }: { p: Programme; onChanged: () => void }) {
  const { can, me } = useAuth();
  const approve = useMutation(() => unwrap<Programme>(api.POST("/api/v1/programmes/{programme_id}/approve", { params: { path: { programme_id: p.id } } })));
  const evaluate = useMutation(() =>
    unwrap<ProgrammeEvaluation>(api.POST("/api/v1/programmes/{programme_id}/evaluate", { params: { path: { programme_id: p.id } } })),
  );
  const evaluation = evaluate.result ?? p.evaluation;
  return (
    <Section
      title={`${p.code} — ${p.name}`}
      actions={
        <>
          <StatusBadge status={p.status} />
          {can("programmes:approve") && p.status === "draft" && (
            <button
              type="button"
              className="btn"
              disabled={approve.pending}
              title={p.created_by === me?.username ? "Segregation of duties: the creator cannot approve" : undefined}
              onClick={async () => {
                if (await approve.run()) onChanged();
              }}
            >
              Approve programme
            </button>
          )}
          {can("programmes:manage") && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={evaluate.pending}
              onClick={async () => {
                if (await evaluate.run()) onChanged();
              }}
            >
              {evaluate.pending ? "Evaluating…" : "Evaluate"}
            </button>
          )}
        </>
      }
    >
      <KeyValues
        columns={3}
        items={[
          ["Objective", p.objective],
          ["Intervention", p.intervention],
          ["Target", p.target],
          ["Population", Object.entries(p.population).map(([k, v]) => `${humanize(k)}: ${v.join(", ")}`).join("; ") || "All obligated employers"],
          ["Denominator", p.denominator_definition],
          ["Baseline window", `${p.baseline[0]} – ${p.baseline[1]}`],
          ["Evaluation window", `${p.evaluation_window[0]} – ${p.evaluation_window[1]}`],
          ["Cohorts", `Intervention ${p.members.intervention ?? 0} · Comparison ${p.members.comparison ?? 0} (comparison share ${(p.comparison_share * 100).toFixed(0)}%)`],
          ["Resource budget", p.resource_budget ?? "—"],
          ["Created / approved by", `${p.created_by} / ${p.approved_by ?? "not yet approved"}`],
        ]}
      />
      <ErrorNotice error={approve.error} />
      <ErrorNotice error={evaluate.error} />
      <div aria-live="polite">{evaluation ? <EvaluationView e={evaluation} /> : <StateMessage state="no_data" title="Not evaluated yet" live="off" />}</div>
    </Section>
  );
}

function EvaluationView({ e }: { e: ProgrammeEvaluation }) {
  const did = e.difference_in_differences;
  return (
    <div className="stack">
      <h3>Evaluation ({fmtDateTime(e.evaluated_at)}, run as at {fmtDateTime(e.as_of)})</h3>
      <p className="m0 small">{e.method}</p>
      <StateMessage state={did === null ? "insufficient_evidence" : "info"} title={did === null ? "Difference-in-differences withheld" : `Difference-in-differences: ${(did * 100).toFixed(1)} percentage points`} live="off">
        {did === null
          ? e.caveat ?? "One or more rates were withheld."
          : "Change in on-time filing for the intervention cohort minus the change for the comparison cohort. Association, not proof of causation; small cohorts are unstable."}
      </StateMessage>
      <div className="grid-2">
        {(["intervention", "comparison"] as const).map((g) => {
          const grp = e.groups[g];
          if (!grp) return null;
          return (
            <div key={g} className="stack-sm">
              <h4>
                {humanize(g)} cohort · {grp.members} members
              </h4>
              <div className="grid-2">
                {grp.baseline && <MetricCard metric={{ ...grp.baseline, label: `Baseline on-time filing` }} headingLevel={4} />}
                {grp.evaluation && <MetricCard metric={{ ...grp.evaluation, label: `Evaluation on-time filing` }} headingLevel={4} />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CreateProgramme({ onCreated }: { onCreated: () => void }) {
  const ref = useReference();
  const [form, setForm] = useState({
    code: "",
    name: "",
    objective: "",
    denominator_definition: "Employers with an active, legally approved PAYE obligation and complete filing coverage",
    baseline_from: "2025-09",
    baseline_to: "2026-02",
    evaluation_from: "2026-03",
    evaluation_to: "2026-08",
    intervention: "",
    target: "",
    resource_budget: "",
    comparison_share: 0.3,
  });
  const [lgas, setLgas] = useState<string[]>([]);
  const m = useMutation(() =>
    unwrap<Programme>(
      api.POST("/api/v1/programmes", {
        body: { ...form, resource_budget: form.resource_budget || null, population: lgas.length ? { lga_codes: lgas } : {} },
      }),
    ),
  );
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: k === "comparison_share" ? Number(e.target.value) : e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await m.run()) onCreated();
  }

  return (
    <Section title="New programme" description="Drafts need approval by a compliance manager other than the creator.">
      <details>
        <summary>Define a programme</summary>
        <form className="stack-sm" onSubmit={submit}>
          <div className="form-grid">
            <Field label="Code" htmlFor="p-code" required hint="Upper-case letters, digits and hyphens">
              <input id="p-code" type="text" pattern="[A-Z0-9\-]{3,40}" value={form.code} onChange={set("code")} required />
            </Field>
            <Field label="Name" htmlFor="p-name" required>
              <input id="p-name" type="text" value={form.name} onChange={set("name")} required />
            </Field>
            <Field label="Objective" htmlFor="p-obj" required>
              <input id="p-obj" type="text" value={form.objective} onChange={set("objective")} required />
            </Field>
            <Field label="Intervention" htmlFor="p-int" required>
              <input id="p-int" type="text" value={form.intervention} onChange={set("intervention")} required />
            </Field>
            <Field label="Target" htmlFor="p-target" required>
              <input id="p-target" type="text" value={form.target} onChange={set("target")} required />
            </Field>
            <Field label="Resource budget" htmlFor="p-budget">
              <input id="p-budget" type="text" value={form.resource_budget} onChange={set("resource_budget")} />
            </Field>
            <Field label="Baseline from" htmlFor="p-bf" required>
              <input id="p-bf" type="text" pattern="\d{4}-\d{2}" value={form.baseline_from} onChange={set("baseline_from")} required />
            </Field>
            <Field label="Baseline to" htmlFor="p-bt" required>
              <input id="p-bt" type="text" pattern="\d{4}-\d{2}" value={form.baseline_to} onChange={set("baseline_to")} required />
            </Field>
            <Field label="Evaluation from" htmlFor="p-ef" required>
              <input id="p-ef" type="text" pattern="\d{4}-\d{2}" value={form.evaluation_from} onChange={set("evaluation_from")} required />
            </Field>
            <Field label="Evaluation to" htmlFor="p-et" required>
              <input id="p-et" type="text" pattern="\d{4}-\d{2}" value={form.evaluation_to} onChange={set("evaluation_to")} required />
            </Field>
            <Field label="Comparison share (0–0.5)" htmlFor="p-share">
              <input id="p-share" type="number" step="0.05" min={0} max={0.5} value={form.comparison_share} onChange={set("comparison_share")} />
            </Field>
            <Field label="Population LGAs" htmlFor="p-lgas" hint="Ctrl/Cmd-click for several; none = state-wide">
              <select id="p-lgas" multiple size={5} value={lgas} onChange={(e) => setLgas([...e.target.selectedOptions].map((o) => o.value))}>
                {ref?.lgas.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Denominator definition" htmlFor="p-den" required>
            <textarea id="p-den" value={form.denominator_definition} onChange={set("denominator_definition")} required />
          </Field>
          <div>
            <button type="submit" className="btn btn-primary" disabled={m.pending}>
              Create draft programme
            </button>
          </div>
          <div aria-live="polite">{m.result && <StateMessage state="approved" title={`Created ${m.result.code}`}>Status: {humanize(m.result.status)}</StateMessage>}</div>
          <ErrorNotice error={m.error} />
        </form>
      </details>
    </Section>
  );
}
