"use client";

import type { CaseDetail, FindingDetail, ReproduceResult, ReviewDecision } from "@ngsirs/contracts";
import { RISK_LABEL, RiskIndicator, StateMessage, StatusBadge } from "@ngsirs/design";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useAsync, useMutation, useReference, useReloadOnConflict } from "@/lib/hooks";
import { AsyncBlock, ErrorNotice, Field, Hash, JsonView, KeyValues, PageHeader, RequirePermission, Section, Yes } from "@/components/ui";
import { api, idempotencyKey, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { REVIEW_DECISIONS } from "@/lib/constants";
import { fmtConfidence, fmtDateTime, humanize } from "@/lib/format";

export default function RiskDetailPage() {
  return (
    <RequirePermission permission="risks:read" what="Risk Detail">
      <RiskDetail />
    </RequirePermission>
  );
}

function RiskDetail() {
  const { id } = useParams<{ id: string }>();
  const finding = useAsync(
    () => unwrap<FindingDetail>(api.GET("/api/v1/risks/{finding_id}", { params: { path: { finding_id: id } } })),
    [id],
  );
  return (
    <AsyncBlock state={finding} what="the finding">
      {(f) => <FindingView f={f} onChanged={(next) => (next ? finding.setData(next) : void finding.reload())} />}
    </AsyncBlock>
  );
}

function FindingView({ f, onChanged }: { f: FindingDetail; onChanged: (next?: FindingDetail) => void }) {
  const { can } = useAuth();
  const obligationRefs = f.evidence_refs.filter((r) => r.startsWith("src:obligation"));
  const obligationRef = typeof f.rule_definition.obligation_ref === "string" ? f.rule_definition.obligation_ref : null;
  const humanEvents = f.events.filter((e) => typeof e.actor === "string" && !String(e.actor).startsWith("system:"));
  const lastDecision = humanEvents[humanEvents.length - 1];
  const holdsText = f.holds.join(", ");

  return (
    <>
      <PageHeader
        eyebrow={
          <>
            <Link href="/risks">Risk Register</Link> / Finding
          </>
        }
        title={`${f.finding_ref} · ${f.rule.id}`}
        description={
          <>
            {f.title} <span className="label-callout">{RISK_LABEL}</span>
          </>
        }
        actions={<StatusBadge status={f.status} />}
      />

      {f.flags.data_hold && (
        <StateMessage state="insufficient_evidence" title="Data hold – insufficient evidence for adverse treatment">
          This finding is held for data verification ({holdsText || "data hold"}). Only internal treatments are allowed until the
          data is verified; no score is published.
        </StateMessage>
      )}
      {f.holds.includes("obligation_unverified") && (
        <StateMessage state="no_obligation">
          The statutory obligation for this subject and period could not be verified. Treat as a review / data-quality signal,
          not a taxpayer culpability indicator.
        </StateMessage>
      )}
      {f.flags.legal_hold && (
        <StateMessage state="deferred" title="Deferred – legal hold">
          A legal hold applies (appeal, stay, extension or legal review). Automated and outward actions are paused.
        </StateMessage>
      )}
      {f.flags.disputed && <StateMessage state="conflict" title="Disputed">The taxpayer or a source disputes this finding.</StateMessage>}
      {f.superseded_by && (
        <StateMessage state="info" title="Superseded">
          Superseded by {f.superseded_by} from a newer rule version. Decisions must be made on the newer finding.
        </StateMessage>
      )}
      {f.status === "approved_for_treatment" && <StateMessage state="approved">Approved for treatment by a human reviewer.</StateMessage>}
      {["closed_confirmed", "closed_not_substantiated", "corrected", "withdrawn"].includes(f.status) && (
        <StateMessage state="closed" title={`Closed – ${humanize(f.status)}`}>
          This finding is in a terminal state.
        </StateMessage>
      )}

      <div className="grid-2">
        <Section title="Indicators">
          <RiskIndicator
            variant="block"
            priority={f.priority_score}
            band={f.priority_band}
            note={f.priority_note}
            confidence={f.indicators.confidence}
            likelihood={f.indicators.likelihood}
            consequence={f.indicators.consequence}
          />
          <KeyValues
            columns={3}
            items={[
              ["Likelihood (1–5)", f.indicators.likelihood ?? "—"],
              ["Consequence (1–5)", f.indicators.consequence ?? (f.priority_note === "data_hold_no_score" ? "Data hold – no score" : "Exposure unknown")],
              ["Evidence confidence (0–1)", fmtConfidence(f.indicators.confidence)],
            ]}
          />
          {f.override && (
            <StateMessage state="info" title="Manager override applied" live="off">
              <JsonView value={f.override} label="Override record" />
            </StateMessage>
          )}
        </Section>
        <Section title="Case facts">
          <KeyValues
            items={[
              [
                "Verified obligation",
                <>
                  {obligationRef ?? "—"}
                  {obligationRefs.map((r) => (
                    <div key={r} className="small">
                      <code>{r}</code>
                    </div>
                  ))}
                  {obligationRefs.length === 0 && <div className="small muted">No obligation record in evidence</div>}
                </>,
              ],
              ["Tax period", f.tax_period ?? "—"],
              ["Relevant law version", f.legal_version ?? "No approved legal version"],
              [
                "Subject",
                f.subject.employer_ref ? (
                  <Link href={`/taxpayers/${encodeURIComponent(f.subject.employer_ref)}`}>
                    {f.employer_name ?? f.subject.employer_ref} ({f.subject.employer_ref})
                  </Link>
                ) : (
                  `${f.subject.type}:${f.subject.id}`
                ),
              ],
              ["LGA", f.lga ?? "—"],
              ["Rule", `${f.rule.id} v${f.rule.version} · ${humanize(f.domain)} · ${humanize(f.signal_class)}`],
              ["Source date (snapshot as at)", fmtDateTime(f.snapshot.as_of as string | null)],
              ["Proposed treatment", humanize(f.treatment)],
              ["Allowed next action", humanize(f.allowed_next_action)],
              [
                "Final human decision",
                lastDecision ? (
                  <>
                    {humanize(String(lastDecision.type))} {lastDecision.to ? `→ ${humanize(String(lastDecision.to))}` : ""} by{" "}
                    {String(lastDecision.actor)} ({fmtDateTime(String(lastDecision.at))})
                    {lastDecision.reason ? <div className="small">“{String(lastDecision.reason)}”</div> : null}
                  </>
                ) : (
                  <span className="muted">None yet — awaiting human review</span>
                ),
              ],
              [
                "Case",
                f.case ? (
                  <Link href={`/cases/${f.case.id}`}>
                    {String(f.case.ref)} · {humanize(String(f.case.stage))}
                  </Link>
                ) : (
                  "No case"
                ),
              ],
            ]}
          />
        </Section>
      </div>

      <Section title="What triggered">
        <p className="m0">{f.explanation}</p>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
          <table className="data">
            <caption>Matched conditions</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Operator</th>
                <th scope="col">Threshold</th>
                <th scope="col">Actual value</th>
              </tr>
            </thead>
            <tbody>
              {f.matched_conditions.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    No condition detail recorded
                  </td>
                </tr>
              )}
              {f.matched_conditions.map((c, i) => {
                const m = c as Record<string, unknown>;
                return (
                  <tr key={i}>
                    <th scope="row">
                      <code>{String(m.field ?? m.series ?? "—")}</code>
                    </th>
                    <td>{String(m.op ?? m.aggregate ?? "—")}</td>
                    <td>
                      <code>{JSON.stringify(m.value)}</code>
                    </td>
                    <td>
                      <code>{JSON.stringify(m.actual)}</code>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid-2">
        <Section title="Evidence" description="Source record references and the snapshot values the rule evaluated.">
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Evidence references</caption>
              <thead>
                <tr>
                  <th scope="col">Reference</th>
                  <th scope="col">Field</th>
                  <th scope="col">Snapshot value</th>
                </tr>
              </thead>
              <tbody>
                {f.evidence.map((e, i) => (
                  <tr key={i}>
                    <th scope="row">
                      <code>{String(e.ref)}</code>
                    </th>
                    <td>{e.field ? <code>{String(e.field)}</code> : "—"}</td>
                    <td>{e.value === null || e.value === undefined ? "—" : <code>{String(e.value)}</code>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section title="Gates">
          <KeyValues
            columns={2}
            items={[
              ["Identity verified", <Yes key="i" value={f.gates.identity_verified} />],
              ["Source coverage complete", <Yes key="c" value={f.gates.coverage_complete} />],
              ["Data hold", <Yes key="d" value={f.gates.data_hold} />],
              ["Legal hold", <Yes key="l" value={f.gates.legal_hold} />],
              ["Disputed", <Yes key="x" value={f.gates.disputed} />],
              ["Holds", f.holds.length ? f.holds.map(humanize).join(", ") : "None"],
            ]}
          />
        </Section>
      </div>

      <div className="grid-2">
        <Section title="Alternative explanations and counter-evidence" description="Reasons the indicator could be wrong. Review each before deciding.">
          <ul className="m0">
            {f.alternative_explanations.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          {f.signals.some((s) => Array.isArray(s.reasons) && (s.reasons as unknown[]).length > 0) ? (
            <div className="stack-sm">
              <h3 className="small">Engine counter-signals</h3>
              <ul className="m0 small">
                {f.signals.map((s, i) => (
                  <li key={i}>
                    {humanize(String(s.outcome))}: {(s.reasons as string[]).map(humanize).join(", ") || "no reasons"} (confidence {fmtConfidence(s.confidence as number | null)})
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="m0 small muted">No counter-evidence was recorded by the engine for this subject and period.</p>
          )}
        </Section>
        <Section title="Exclusions checked" description="Each exclusion was evaluated and did not apply; had it applied, the finding would have been suppressed.">
          <ul className="m0">
            {f.exclusions_checked.map((x) => (
              <li key={x}>
                <code>{x}</code> — {humanize(x)}
              </li>
            ))}
            {f.exclusions_checked.length === 0 && <li className="muted">This rule defines no exclusions.</li>}
          </ul>
        </Section>
      </div>

      <ReproducePanel f={f} />

      <div className="grid-2">
        {can("risks:review") || can("risks:legal_hold") ? <ReviewForm f={f} onChanged={onChanged} /> : null}
        {can("cases:create") && <OpenCaseForm f={f} />}
        {can("risks:override") && <OverrideForm f={f} onChanged={onChanged} />}
      </div>

      <Section title="Event log and reviewer decisions">
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
          <table className="data">
            <caption className="ng-visually-hidden">Finding event log</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Event</th>
                <th scope="col">Transition</th>
                <th scope="col">Actor</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {f.events.map((e, i) => (
                <tr key={i}>
                  <td className="nowrap">{fmtDateTime(String(e.at))}</td>
                  <th scope="row">{humanize(String(e.type))}</th>
                  <td>{e.from || e.to ? `${humanize(String(e.from ?? "—"))} → ${humanize(String(e.to ?? "—"))}` : "—"}</td>
                  <td>{String(e.actor)}</td>
                  <td>{e.reason ? String(e.reason) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Rule definition" description={`The exact versioned definition evaluated (content hash ${String(f.snapshot.rule_content_hash ?? "—").slice(0, 16)}…).`}>
        <details>
          <summary>Show JSON definition</summary>
          <JsonView value={f.rule_definition} label="Rule definition JSON" />
        </details>
      </Section>
    </>
  );
}

function ReproducePanel({ f }: { f: FindingDetail }) {
  const m = useMutation(() =>
    unwrap<ReproduceResult>(api.POST("/api/v1/risks/{finding_id}/reproduce", { params: { path: { finding_id: f.finding_id } } })),
  );
  return (
    <Section
      title="Source, snapshot and reproducibility"
      actions={
        <button type="button" className="btn btn-primary" onClick={() => void m.run()} disabled={m.pending}>
          {m.pending ? "Reproducing…" : "Reproduce score"}
        </button>
      }
    >
      <KeyValues
        columns={3}
        items={[
          ["Snapshot as at", fmtDateTime(f.snapshot.as_of as string | null)],
          ["Snapshot facts hash", <Hash key="s" value={f.snapshot.facts_hash as string | null} />],
          ["Evaluation run", <Hash key="r" value={f.snapshot.run_id as string | null} />],
          ["Rule set hash", <Hash key="rs" value={f.snapshot.rule_set_hash as string | null} />],
          ["Rule content hash", <Hash key="rc" value={f.snapshot.rule_content_hash as string | null} />],
          ["Finding created", fmtDateTime(f.created_at)],
        ]}
      />
      <div aria-live="polite">
        {m.result && (
          <StateMessage
            state={m.result.reproduced ? "approved" : "conflict"}
            title={m.result.reproduced ? "Reproduced: yes — identical outcome from the same snapshot and rule version" : "Reproduced: no — outcome differs"}
          >
            <KeyValues
              columns={2}
              items={[
                ["Recomputed outcome hash", <Hash key="o" value={m.result.outcome_hash} len={24} />],
                ["Stored outcome hash", <Hash key="so" value={m.result.stored_outcome_hash} len={24} />],
                ["Rule", m.result.rule],
                ["Snapshot", <Hash key="sn" value={m.result.snapshot} len={24} />],
              ]}
            />
          </StateMessage>
        )}
      </div>
      <ErrorNotice error={m.error} />
    </Section>
  );
}

function ReviewForm({ f, onChanged }: { f: FindingDetail; onChanged: (next?: FindingDetail) => void }) {
  const { can } = useAuth();
  const options = REVIEW_DECISIONS.filter((d) => can(d.permission));
  const [decision, setDecision] = useState<ReviewDecision | "">("");
  const [reason, setReason] = useState("");
  const m = useMutation((body: { decision: ReviewDecision; reason: string }) =>
    unwrap<FindingDetail>(
      api.POST("/api/v1/risks/{finding_id}/review", {
        params: { path: { finding_id: f.finding_id }, header: { "Idempotency-Key": idempotencyKey() } },
        body: { ...body, expected_version: f.version },
      }),
    ),
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!decision) return;
    const r = await m.run({ decision, reason });
    if (r) {
      setReason("");
      setDecision("");
      onChanged(r);
    }
  }
  useReloadOnConflict(m.error, onChanged);

  return (
    <Section title="Record review decision" description="Every decision requires a reason and is written to the finding event log and audit chain.">
      <form onSubmit={submit} className="stack-sm">
        <Field label="Decision" htmlFor="rv-decision" required>
          <select id="rv-decision" value={decision} onChange={(e) => setDecision(e.target.value as ReviewDecision)} required>
            <option value="">Choose…</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Reason" htmlFor="rv-reason" required hint="Minimum 3 characters. State the evidence relied on.">
          <textarea id="rv-reason" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} aria-describedby="rv-reason-hint" />
        </Field>
        <div>
          <button type="submit" className="btn btn-primary" disabled={m.pending || !decision || reason.trim().length < 3}>
            {m.pending ? "Saving…" : "Record decision"}
          </button>
        </div>
        <div aria-live="polite">{m.result && <StateMessage state="approved" title="Decision recorded">Finding is now {humanize(m.result.status)}.</StateMessage>}</div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function OverrideForm({ f, onChanged }: { f: FindingDetail; onChanged: (next?: FindingDetail) => void }) {
  const [likelihood, setLikelihood] = useState("");
  const [consequence, setConsequence] = useState("");
  const [reason, setReason] = useState("");
  const m = useMutation(() =>
    unwrap<FindingDetail>(
      api.POST("/api/v1/risks/{finding_id}/override", {
        params: { path: { finding_id: f.finding_id } },
        body: {
          likelihood: likelihood ? Number(likelihood) : null,
          consequence: consequence ? Number(consequence) : null,
          reason,
          expected_version: f.version,
        },
      }),
    ),
  );
  useReloadOnConflict(m.error, onChanged);
  return (
    <Section title="Manager override" description="Adjust likelihood or consequence with a recorded reason. The engine outcome is retained alongside.">
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await m.run();
          if (r) {
            setReason("");
            onChanged(r);
          }
        }}
      >
        <div className="form-grid">
          <Field label="Likelihood (1–5)" htmlFor="ov-l">
            <select id="ov-l" value={likelihood} onChange={(e) => setLikelihood(e.target.value)}>
              <option value="">Keep ({f.indicators.likelihood ?? "unknown"})</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </Field>
          <Field label="Consequence (1–5)" htmlFor="ov-c">
            <select id="ov-c" value={consequence} onChange={(e) => setConsequence(e.target.value)}>
              <option value="">Keep ({f.indicators.consequence ?? "exposure unknown"})</option>
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Reason" htmlFor="ov-reason" required>
          <textarea id="ov-reason" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} />
        </Field>
        <div>
          <button type="submit" className="btn" disabled={m.pending || reason.trim().length < 3 || (!likelihood && !consequence)}>
            Apply override
          </button>
        </div>
        <div aria-live="polite">{m.result && <StateMessage state="approved" title="Override recorded" />}</div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function OpenCaseForm({ f }: { f: FindingDetail }) {
  const ref = useReference();
  const router = useRouter();
  const { me } = useAuth();
  const [treatment, setTreatment] = useState("");
  const [rationale, setRationale] = useState("");
  const [assignee, setAssignee] = useState(me?.username ?? "");
  const [sla, setSla] = useState(14);
  const m = useMutation(() =>
    unwrap<CaseDetail>(
      api.POST("/api/v1/cases", {
        params: { header: { "Idempotency-Key": idempotencyKey() } },
        body: { finding_id: f.finding_id, treatment: treatment || null, rationale, assigned_to: assignee || null, sla_days: sla },
      }),
    ),
  );

  // The API attaches the most recent case; a closed or rejected one no longer blocks a new case.
  if (f.case && !["closed", "rejected"].includes(String(f.case.stage))) {
    return (
      <Section title="Case">
        <p className="m0">
          An active case exists: <Link href={`/cases/${f.case.id}`}>{String(f.case.ref)}</Link> ({humanize(String(f.case.stage))}).
        </p>
      </Section>
    );
  }
  const officers = (ref?.users ?? []).filter((u) => u.roles.some((r) => ["compliance_officer", "compliance_manager", "risk_analyst", "data_steward", "audit_officer"].includes(r)));
  return (
    <Section title="Open case" description="Creates a case pending manager approval. The creator cannot approve their own case.">
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          const c = await m.run();
          if (c) router.push(`/cases/${c.id}`);
        }}
      >
        <Field label="Treatment" htmlFor="oc-treatment" hint={`Default: ${humanize(f.treatment)}`}>
          <select id="oc-treatment" value={treatment} onChange={(e) => setTreatment(e.target.value)}>
            <option value="">Proposed treatment ({humanize(f.treatment)})</option>
            {Object.entries(ref?.treatments ?? {}).map(([k, t]) => (
              <option key={k} value={k} disabled={f.flags.data_hold && t.outward}>
                {t.label}
                {t.outward ? " (outward)" : " (internal)"}
                {f.flags.data_hold && t.outward ? " — not allowed on data hold" : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Rationale" htmlFor="oc-rationale" required>
          <textarea id="oc-rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} required minLength={3} />
        </Field>
        <div className="form-grid">
          <Field label="Assign to" htmlFor="oc-assignee">
            <select id="oc-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Unassigned</option>
              {officers.map((u) => (
                <option key={u.username} value={u.username}>
                  {u.display_name} ({u.username})
                </option>
              ))}
            </select>
          </Field>
          <Field label="SLA (days)" htmlFor="oc-sla">
            <input id="oc-sla" type="number" min={1} max={180} value={sla} onChange={(e) => setSla(Number(e.target.value))} />
          </Field>
        </div>
        <div>
          <button type="submit" className="btn btn-primary" disabled={m.pending || rationale.trim().length < 3}>
            {m.pending ? "Opening…" : "Open case"}
          </button>
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}
