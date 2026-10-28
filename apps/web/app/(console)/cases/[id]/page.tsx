"use client";

import type { CaseDetail, EvidencePacketResult, FindingDetail, FindingOutcome } from "@ngsirs/contracts";
import { RISK_LABEL, RiskIndicator, StateMessage, StatusBadge } from "@ngsirs/design";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { PurposeSelect } from "@/components/PurposeSelect";
import { AsyncBlock, ErrorNotice, Field, Hash, JsonView, KeyValues, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, idempotencyKey, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ACTION_TYPES, APPROVED_TEMPLATES, FINDING_OUTCOMES, OUTWARD_BLOCKERS } from "@/lib/constants";
import { useAsync, useMutation, useReference, useReloadOnConflict } from "@/lib/hooks";
import { fmtConfidence, fmtDateTime, humanize } from "@/lib/format";

const OPEN_STAGES = ["approved", "in_progress", "awaiting_response", "outcome_recorded"];

export default function CaseDetailPage() {
  return (
    <RequirePermission permission="cases:read" what="this case">
      <CaseScreen />
    </RequirePermission>
  );
}

function CaseScreen() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const c = useAsync(() => unwrap<CaseDetail>(api.GET("/api/v1/cases/{case_id}", { params: { path: { case_id: id } } })), [id]);
  const findingId = c.data?.finding_id;
  const finding = useAsync(
    () => unwrap<FindingDetail>(api.GET("/api/v1/risks/{finding_id}", { params: { path: { finding_id: findingId! } } })),
    [findingId, c.data?.version],
    !!findingId && can("risks:read"),
  );
  return (
    <AsyncBlock state={c} what="the case">
      {(d) => <CaseView c={d} f={finding.data} update={(n) => (n ? c.setData(n) : void c.reload())} />}
    </AsyncBlock>
  );
}

function stageMessage(c: CaseDetail) {
  switch (c.stage) {
    case "pending_approval":
      return (
        <StateMessage state="deferred" title="Pending manager approval">
          No action can be recorded until a compliance manager other than the creator ({c.created_by}) approves this case.
        </StateMessage>
      );
    case "approved":
      return (
        <StateMessage state="approved">
          Approved by {c.approved_by} on {fmtDateTime(c.approved_at)}.
        </StateMessage>
      );
    case "closed":
      return <StateMessage state="closed" title={`Closed – ${humanize(c.outcome)}`}>No further actions can be recorded.</StateMessage>;
    case "rejected":
      return <StateMessage state="closed" title="Rejected">The manager rejected this case. No action may be taken.</StateMessage>;
    default:
      return null;
  }
}

function CaseView({ c, f, update }: { c: CaseDetail; f: FindingDetail | null; update: (n?: CaseDetail) => void }) {
  const { can } = useAuth();
  const summary = c.finding;
  const lastHuman = f?.events.filter((e) => !String(e.actor).startsWith("system:")).at(-1);
  return (
    <>
      <PageHeader
        eyebrow={
          <>
            <Link href="/cases">Intervention Queue</Link> / Case
          </>
        }
        title={c.case_ref}
        description={
          <>
            {c.treatment_label ?? humanize(c.treatment)} · {c.employer_name ?? c.employer_ref} · <span className="label-callout">{RISK_LABEL}</span>
          </>
        }
        actions={<StatusBadge status={c.stage} />}
      />
      {stageMessage(c)}
      {c.overdue && <StateMessage state="conflict" title="Overdue against SLA">Due {fmtDateTime(c.due_at)}.</StateMessage>}

      <div className="grid-2">
        <Section title="Case and finding facts">
          <KeyValues
            items={[
              [
                "Verified obligation",
                f ? (
                  <>
                    {String(f.rule_definition.obligation_ref ?? "—")}
                    {f.evidence_refs
                      .filter((r) => r.startsWith("src:obligation"))
                      .map((r) => (
                        <div key={r} className="small">
                          <code>{r}</code>
                        </div>
                      ))}
                  </>
                ) : (
                  "See finding"
                ),
              ],
              ["Tax period", c.tax_period ?? "—"],
              ["Trigger", f?.explanation ?? summary?.explanation ?? "—"],
              [
                "Evidence",
                f ? (
                  <ul className="m0 small">
                    {f.evidence.map((e, i) => (
                      <li key={i}>
                        <code>{String(e.ref)}</code>
                        {e.field ? ` · ${String(e.field)} = ${String(e.value)}` : ""}
                      </li>
                    ))}
                  </ul>
                ) : (
                  "—"
                ),
              ],
              ["Source date (snapshot as at)", f ? fmtDateTime(f.snapshot.as_of as string) : "—"],
              ["Confidence", fmtConfidence(summary?.indicators.confidence)],
              ["Exclusions checked", f ? f.exclusions_checked.map(humanize).join(", ") || "None defined" : "—"],
              ["Relevant law version", f?.legal_version ?? "—"],
              ["Proposed action", `${c.treatment_label ?? humanize(c.treatment)} — ${c.rationale}`],
              [
                "Final human decision",
                c.stage === "closed"
                  ? `Closed as ${humanize(c.outcome)}`
                  : c.stage === "rejected"
                    ? "Rejected by manager"
                    : c.approved_by
                      ? `Approved by ${c.approved_by} (${fmtDateTime(c.approved_at)})`
                      : lastHuman
                        ? `${humanize(String(lastHuman.type))} by ${String(lastHuman.actor)}`
                        : "Awaiting approval",
              ],
            ]}
          />
        </Section>
        <div className="stack">
          <Section title="Finding">
            {summary ? (
              <>
                <p className="m0">
                  <Link href={`/risks/${c.finding_id}`}>{summary.finding_ref}</Link> · <code>{summary.rule.id}</code> v{summary.rule.version} ·{" "}
                  <StatusBadge status={summary.status} />
                </p>
                <RiskIndicator
                  variant="block"
                  priority={summary.priority_score}
                  band={summary.priority_band}
                  note={summary.priority_note}
                  confidence={summary.indicators.confidence}
                  likelihood={summary.indicators.likelihood}
                  consequence={summary.indicators.consequence}
                />
              </>
            ) : (
              <p className="m0 muted">Finding unavailable.</p>
            )}
          </Section>
          <Section title="Workflow">
            <KeyValues
              items={[
                ["Assigned to", c.assigned_to ?? "Unassigned"],
                ["Created by", `${c.created_by} · ${fmtDateTime(c.created_at)}`],
                ["Approved by", c.approved_by ? `${c.approved_by} · ${fmtDateTime(c.approved_at)}` : "—"],
                ["SLA due", fmtDateTime(c.due_at)],
                ["Legal hold", c.legal_hold ? "Yes" : "No"],
                [
                  "Outward taxpayer contact",
                  c.outward_permitted && c.outward_blockers.length === 0 ? (
                    <StatusBadge tone="success">Permitted (approved templates only)</StatusBadge>
                  ) : (
                    <>
                      <StatusBadge tone="neutral">Not permitted</StatusBadge>
                      <ul className="m0 small">
                        {c.outward_blockers.map((b) => (
                          <li key={b}>{OUTWARD_BLOCKERS[b] ?? humanize(b)}</li>
                        ))}
                        {c.outward_blockers.length === 0 && <li>Awaiting approval</li>}
                      </ul>
                    </>
                  ),
                ],
              ]}
            />
          </Section>
        </div>
      </div>

      <div className="grid-2">
        {can("cases:approve") && c.stage === "pending_approval" && <ApprovePanel c={c} update={update} />}
        {can("cases:assign") && !["closed", "rejected"].includes(c.stage) && <AssignPanel c={c} update={update} />}
        {can("cases:act") && OPEN_STAGES.includes(c.stage) && <ActionPanel c={c} update={update} />}
        {can("cases:close") && OPEN_STAGES.includes(c.stage) && <ClosePanel c={c} update={update} />}
        {can("evidence:export") && <EvidencePanel c={c} update={update} />}
      </div>

      <Section title="Actions and follow-up">
        {c.actions.length === 0 ? (
          <StateMessage state="no_data" title="No actions recorded yet" />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Case actions</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Action</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Template · delivery</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Evidence / outcome</th>
                  <th scope="col">Next due</th>
                </tr>
              </thead>
              <tbody>
                {c.actions.map((a) => (
                  <tr key={String(a.id)}>
                    <td className="nowrap">{fmtDateTime(String(a.at))}</td>
                    <th scope="row">{humanize(String(a.type))}</th>
                    <td>{String(a.detail)}</td>
                    <td>
                      {a.template ? <code>{String(a.template)}</code> : "—"}
                      {a.delivery_status ? (
                        <div>
                          <span className="delivery-status">{String(a.delivery_status)}</span>
                          {a.delivery_status === "not_sent_demo_environment" && (
                            <div className="small">Not sent: demo environment. No message left the platform.</div>
                          )}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      {String(a.actor)}
                      {a.approved_by ? <div className="small muted">approved by {String(a.approved_by)}</div> : null}
                    </td>
                    <td>
                      {a.evidence_ref ? <code>{String(a.evidence_ref)}</code> : null}
                      {a.outcome ? <div>{String(a.outcome)}</div> : null}
                      {!a.evidence_ref && !a.outcome && "—"}
                    </td>
                    <td>{a.next_due_at ? fmtDateTime(String(a.next_due_at)) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </>
  );
}

type Update = (n?: CaseDetail) => void;

function ApprovePanel({ c, update }: { c: CaseDetail; update: Update }) {
  const { me } = useAuth();
  const [note, setNote] = useState("");
  const m = useMutation((decision: "approve" | "reject") =>
    decision === "approve"
      ? unwrap<CaseDetail>(api.POST("/api/v1/cases/{case_id}/approve", { params: { path: { case_id: c.id } }, body: { note, expected_version: c.version } }))
      : unwrap<CaseDetail>(api.POST("/api/v1/cases/{case_id}/reject", { params: { path: { case_id: c.id } }, body: { note, expected_version: c.version } })),
  );
  useReloadOnConflict(m.error, update);
  const isCreator = me?.username === c.created_by;
  return (
    <Section title="Manager decision" description="Maker-checker: the case creator cannot approve or reject it.">
      {isCreator && (
        <StateMessage state="info" title="You created this case" live="off">
          Segregation of duties applies: another compliance manager must decide it. The API will refuse your decision.
        </StateMessage>
      )}
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
          const r = await m.run(submitter?.value === "reject" ? "reject" : "approve");
          if (r) update(r);
        }}
      >
        <Field label="Decision note" htmlFor="ap-note" required>
          <textarea id="ap-note" value={note} onChange={(e) => setNote(e.target.value)} required minLength={3} />
        </Field>
        <div className="row">
          <button type="submit" name="decision" value="approve" className="btn btn-primary" disabled={m.pending || note.trim().length < 3}>
            Approve case
          </button>
          <button type="submit" name="decision" value="reject" className="btn btn-danger" disabled={m.pending || note.trim().length < 3}>
            Reject case
          </button>
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function AssignPanel({ c, update }: { c: CaseDetail; update: Update }) {
  const ref = useReference();
  const [assignee, setAssignee] = useState(c.assigned_to ?? "");
  const m = useMutation(() =>
    unwrap<CaseDetail>(api.POST("/api/v1/cases/{case_id}/assign", { params: { path: { case_id: c.id } }, body: { assignee, expected_version: c.version } })),
  );
  useReloadOnConflict(m.error, update);
  return (
    <Section title="Assign">
      <form
        className="row-end"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await m.run();
          if (r) update(r);
        }}
      >
        <Field label="Assignee" htmlFor="as-user">
          <select id="as-user" value={assignee} onChange={(e) => setAssignee(e.target.value)} required>
            <option value="">Choose…</option>
            {(ref?.users ?? []).map((u) => (
              <option key={u.username} value={u.username}>
                {u.display_name} ({u.roles.map(humanize).join(", ")})
              </option>
            ))}
          </select>
        </Field>
        <button type="submit" className="btn" disabled={!assignee || m.pending}>
          Assign
        </button>
      </form>
      <div aria-live="polite">{m.result && <p className="m0 small">Assigned to {m.result.assigned_to}.</p>}</div>
      <ErrorNotice error={m.error} />
    </Section>
  );
}

function ActionPanel({ c, update }: { c: CaseDetail; update: Update }) {
  const { hasRole } = useAuth();
  const [type, setType] = useState("note");
  const [detail, setDetail] = useState("");
  const [template, setTemplate] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [outcome, setOutcome] = useState("");
  const [nextDue, setNextDue] = useState("");
  const contactAllowed = c.outward_permitted && c.outward_blockers.length === 0;
  const m = useMutation(() =>
    unwrap<CaseDetail>(
      api.POST("/api/v1/cases/{case_id}/actions", {
        params: { path: { case_id: c.id }, header: { "Idempotency-Key": idempotencyKey() } },
        body: {
          action_type: type,
          detail,
          template_code: type === "contact_taxpayer" ? template || null : null,
          evidence_ref: evidenceRef || null,
          outcome: outcome || null,
          next_due_at: nextDue ? new Date(nextDue).toISOString() : null,
          expected_version: c.version,
        },
      }),
    ),
  );
  useReloadOnConflict(m.error, update);
  const last = m.result?.actions.at(-1);
  return (
    <Section title="Record action" description="Actions are appended to the case and the audit chain.">
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await m.run();
          if (r) {
            setDetail("");
            setEvidenceRef("");
            setOutcome("");
            update(r);
          }
        }}
      >
        <Field label="Action type" htmlFor="ac-type" required>
          <select id="ac-type" value={type} onChange={(e) => setType(e.target.value)}>
            {ACTION_TYPES.map((a) => (
              <option
                key={a.value}
                value={a.value}
                disabled={(a.value === "contact_taxpayer" && !contactAllowed) || (a.value === "audit_finding" && !hasRole("audit_officer"))}
              >
                {a.label}
                {a.value === "contact_taxpayer" && !contactAllowed ? " — not permitted for this case" : ""}
              </option>
            ))}
          </select>
        </Field>
        {type === "contact_taxpayer" && (
          <>
            <Field label="Approved communication template" htmlFor="ac-template" required>
              <select id="ac-template" value={template} onChange={(e) => setTemplate(e.target.value)} required>
                <option value="">Choose…</option>
                {APPROVED_TEMPLATES.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.label} — {t.code}
                  </option>
                ))}
              </select>
            </Field>
            <p className="notice-strong m0">Demo environment: contact is recorded with delivery status &ldquo;not_sent_demo_environment&rdquo;. Nothing is sent to any taxpayer.</p>
          </>
        )}
        <Field label="Detail" htmlFor="ac-detail" required>
          <textarea id="ac-detail" value={detail} onChange={(e) => setDetail(e.target.value)} required />
        </Field>
        <div className="form-grid">
          <Field label="Evidence reference" htmlFor="ac-evidence" hint="e.g. payment receipt or document ID">
            <input id="ac-evidence" type="text" value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)} />
          </Field>
          <Field label="Outcome" htmlFor="ac-outcome">
            <input id="ac-outcome" type="text" value={outcome} onChange={(e) => setOutcome(e.target.value)} />
          </Field>
          <Field label="Next follow-up due" htmlFor="ac-next">
            <input id="ac-next" type="datetime-local" value={nextDue} onChange={(e) => setNextDue(e.target.value)} />
          </Field>
        </div>
        <div>
          <button type="submit" className="btn btn-primary" disabled={m.pending || !detail.trim() || (type === "contact_taxpayer" && !template)}>
            Record action
          </button>
        </div>
        <div aria-live="polite">
          {last && (
            <StateMessage state="approved" title={`Recorded: ${humanize(String(last.type))}`}>
              {last.delivery_status ? (
                <p className="m0">
                  Delivery status: <span className="delivery-status">{String(last.delivery_status)}</span>
                </p>
              ) : null}
            </StateMessage>
          )}
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function ClosePanel({ c, update }: { c: CaseDetail; update: Update }) {
  const [outcome, setOutcome] = useState<FindingOutcome | "">("");
  const [note, setNote] = useState("");
  const m = useMutation(() =>
    unwrap<CaseDetail>(
      api.POST("/api/v1/cases/{case_id}/close", {
        params: { path: { case_id: c.id } },
        body: { finding_outcome: outcome as FindingOutcome, note, expected_version: c.version },
      }),
    ),
  );
  useReloadOnConflict(m.error, update);
  return (
    <Section title="Close case" description="Closing records the final finding outcome. Missing system matching is not proof of non-payment.">
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await m.run();
          if (r) update(r);
        }}
      >
        <Field label="Finding outcome" htmlFor="cl-outcome" required>
          <select id="cl-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as FindingOutcome)} required>
            <option value="">Choose…</option>
            {FINDING_OUTCOMES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Closing note" htmlFor="cl-note" required>
          <textarea id="cl-note" value={note} onChange={(e) => setNote(e.target.value)} required minLength={3} />
        </Field>
        <div>
          <button type="submit" className="btn" disabled={!outcome || note.trim().length < 3 || m.pending}>
            Close case
          </button>
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function EvidencePanel({ c, update }: { c: CaseDetail; update: Update }) {
  const [purpose, setPurpose] = useState("");
  const m = useMutation(() =>
    unwrap<EvidencePacketResult>(
      api.POST("/api/v1/cases/{case_id}/evidence-packet", { params: { path: { case_id: c.id }, header: { "X-Purpose": purpose } } }),
    ),
  );
  const exportable = !["pending_approval", "rejected"].includes(c.stage);
  return (
    <Section title="Signed evidence packet" description="Exports a signed, hashed desk-review packet. The declared purpose is audited.">
      {!exportable && <StateMessage state="deferred">Evidence packets are exported only for approved desk-review cases.</StateMessage>}
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await m.run()) update();
        }}
      >
        <PurposeSelect id="ev-purpose" value={purpose} onChange={setPurpose} preferred="desk_review" />
        <div>
          <button type="submit" className="btn btn-primary" disabled={!purpose || m.pending || !exportable}>
            Export evidence packet
          </button>
        </div>
      </form>
      <div aria-live="polite">
        {m.result && (
          <StateMessage state="approved" title="Evidence packet signed">
            <KeyValues
              columns={1}
              items={[
                ["SHA-256", <code key="h" className="hash" data-testid="packet-sha">{m.result.sha256}</code>],
                ["Signature", <code key="s" className="hash">{m.result.signature}</code>],
                ["Algorithm · key ID", `${m.result.algorithm} · ${m.result.key_id}`],
              ]}
            />
            <details>
              <summary>Packet contents</summary>
              <JsonView value={m.result.packet} label="Evidence packet JSON" />
            </details>
          </StateMessage>
        )}
      </div>
      <ErrorNotice error={m.error} />
      {c.packets.length > 0 && (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
          <table className="data">
            <caption>Previous exports</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">By</th>
                <th scope="col">Purpose</th>
                <th scope="col">SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {c.packets.map((p) => (
                <tr key={String(p.sha256) + String(p.at)}>
                  <td className="nowrap">{fmtDateTime(String(p.at))}</td>
                  <td>{String(p.exported_by)}</td>
                  <td>{humanize(String(p.purpose))}</td>
                  <td>
                    <Hash value={String(p.sha256)} len={20} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
