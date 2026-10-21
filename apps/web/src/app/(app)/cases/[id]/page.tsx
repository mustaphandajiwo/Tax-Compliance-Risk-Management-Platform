"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { isSlaBreached } from "@/components/CaseTable";
import { EvidencePanel } from "@/components/EvidencePanel";
import { ActionResult, Badge, Card, ConfidenceBadge, ErrorBox, Loading, NoAccess, Notice, PageHead, ReasonField, reasonOk, SelectField, StatusBadge, TextArea, TextField, useAction, useAsync } from "@/components/ui";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, dateTime, humanize, money, num } from "@/lib/format";
import { CONTACT_CHANNELS, DISPOSITIONS, INTERVENTIONS, REFERRALS } from "@/lib/reference";
import type { CaseDetail, UserOut } from "@/lib/types";
import { userName, useUserDirectory } from "@/lib/users";

const MAIN_STAGES = ["open", "pending_approval", "approved", "in_progress", "closed"];
const AUDIT_STAGES = ["open", "audit_referral_pending", "audit_in_progress", "closed"];

const ACTION_LABELS: Record<string, string> = {
  create: "Case opened",
  submit_proposal: "Submit intervention proposal",
  approve_proposal: "Approve proposal",
  return_for_revision: "Return for revision",
  start_work: "Start work",
  record_contact: "Record taxpayer contact",
  refer_audit: "Refer for audit / investigation",
  approve_audit: "Approve audit referral",
  reject_audit: "Reject audit referral",
  record_audit_findings: "Record audit findings",
  reassign: "Reassign",
  close: "Close case",
};

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { can, me } = useAuth();
  const allowed = can("cases.read");
  const res = useAsync(() => apiGet("/v1/cases/{case_id}", { path: { case_id: id } }), [id], allowed);
  const users = useUserDirectory(allowed && can("users.read"));

  if (!allowed) return <NoAccess permission="cases.read" />;
  if (res.error && !res.data) return <ErrorBox error={res.error} onRetry={res.reload} />;
  if (!res.data) return <Loading label="Loading case…" />;
  const c = res.data;
  const a = c.assessment;
  const breached = c.sla_breached || isSlaBreached(c);
  const auditPath = c.status.startsWith("audit") || c.actions.some((x) => x.action === "refer_audit" || x.action === "approve_audit");
  const stages = auditPath ? AUDIT_STAGES : MAIN_STAGES;
  const currentIdx = stages.indexOf(c.status);

  return (
    <>
      <PageHead
        title={`Case ${c.reference}`}
        description={
          <>
            <Link href="/cases">Cases</Link> / {c.taxpayer_name ? <Link href={`/taxpayers/${c.taxpayer_id}`}>{c.taxpayer_name}</Link> : "Taxpayer"} · opened {date(c.created_at)}
          </>
        }
        actions={<StatusBadge status={c.status} />}
      />
      <div className="stack">
        <nav aria-label="Case stage" className="stage-track">
          {stages.map((s, i) => (
            <span key={s} className={`stage ${i < currentIdx ? "done" : i === currentIdx ? "current" : ""}`} aria-current={i === currentIdx ? "step" : undefined}>
              {humanize(s)}
            </span>
          ))}
        </nav>

        <div className="grid-3">
          <Card title="Status & SLA">
            <dl className="kv">
              <dt>Stage</dt>
              <dd>
                <StatusBadge status={c.status} />
              </dd>
              <dt>SLA due</dt>
              <dd>
                {date(c.sla_due)} {breached ? <Badge tone="danger">SLA breached</Badge> : c.status !== "closed" ? <Badge tone="ok">Within SLA</Badge> : null}
              </dd>
              <dt>Assignee</dt>
              <dd>{userName(users, c.assignee_id, me?.id, me?.full_name)}</dd>
              <dt>Owner</dt>
              <dd>{userName(users, c.owner_id, me?.id, me?.full_name)}</dd>
              <dt>Proposed intervention</dt>
              <dd>{humanize(c.proposed_intervention)}</dd>
            </dl>
          </Card>
          <Card title="Outcome">
            <dl className="kv">
              <dt>Disposition</dt>
              <dd>{humanize(c.disposition)}</dd>
              <dt>Outcome</dt>
              <dd>{c.outcome ?? "—"}</dd>
              <dt>Amount collected</dt>
              <dd>{money(c.amount_collected)}</dd>
              <dt>Closed</dt>
              <dd>{dateTime(c.closed_at)}</dd>
            </dl>
          </Card>
          <Card title="Assessment summary" actions={can("risk.read") ? <Link className="small" href={`/workbench?assessment=${a.id}`}>Open in workbench</Link> : undefined}>
            <dl className="kv">
              <dt>Score</dt>
              <dd>{num(a.score)} / 100 (indicator)</dd>
              <dt>Confidence</dt>
              <dd>
                <ConfidenceBadge value={a.confidence} />
              </dd>
              <dt>Tax · period</dt>
              <dd>
                {a.tax_type} · {a.period}
              </dd>
              <dt>Exposure scenario</dt>
              <dd>{money(a.exposure_estimate)}</dd>
              <dt>Reasons</dt>
              <dd>
                <div className="chips">
                  {a.reason_codes.map((r) => (
                    <Badge key={r} tone={r === "REP-001" ? "warn" : "outline"}>
                      {r}
                    </Badge>
                  ))}
                </div>
              </dd>
              <dt>Model</dt>
              <dd>
                v{a.model_version} · {a.ruleset_version}
              </dd>
            </dl>
            {a.suppressed && (
              <p className="small" style={{ color: "var(--warn)", marginTop: 8 }}>
                Low confidence — only data correction or no action may be proposed.
              </p>
            )}
          </Card>
        </div>

        <div className="split">
          <div className="stack">
            <ActionForm c={c} onDone={res.setData} />
            <Card title={`Action history (${c.actions.length})`}>
              <ol className="timeline">
                {[...c.actions].reverse().map((x) => (
                  <li key={x.id}>
                    <div className="row-between">
                      <strong>{ACTION_LABELS[x.action] ?? humanize(x.action)}</strong>
                      <span className="tiny muted">{dateTime(x.created_at)}</span>
                    </div>
                    <div className="small">
                      {x.actor_name ?? userName(users, x.actor_id)} · <StatusBadge status={x.from_status === "-" ? null : x.from_status} /> → <StatusBadge status={x.to_status} />
                    </div>
                    <div className="small">
                      <span className="muted">Justification:</span> {x.justification}
                    </div>
                    {Object.keys(x.payload).length > 0 && (
                      <div className="tiny muted">
                        {Object.entries(x.payload)
                          .map(([k, v]) =>
                            k === "assignee_id" && typeof v === "string"
                              ? `Assignee: ${userName(users, v)}`
                              : k.endsWith("_id") && typeof v === "string"
                                ? `${humanize(k.replace(/_id$/, ""))}: ${v.slice(0, 8)}`
                                : `${humanize(k)}: ${humanize(String(v))}`,
                          )
                          .join(" · ")}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </Card>
          </div>
          <div className="stack">
            <Card title={`Interventions (${c.interventions.length})`} pad={false}>
              {c.interventions.length === 0 ? (
                <p className="muted card-body mb-0">No intervention proposed yet.</p>
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Type</th>
                        <th scope="col">Status</th>
                        <th scope="col">Rationale</th>
                        <th scope="col">Proposed / approved by</th>
                        <th scope="col">Executed</th>
                        <th scope="col">Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {c.interventions.map((iv) => (
                        <tr key={iv.id}>
                          <td>{humanize(iv.type)}</td>
                          <td>
                            <StatusBadge status={iv.status} />
                          </td>
                          <td className="small">{iv.rationale}</td>
                          <td className="small">
                            {userName(users, iv.proposed_by, me?.id, me?.full_name)}
                            <br />
                            {iv.approved_by ? `${userName(users, iv.approved_by, me?.id, me?.full_name)} · ${dateTime(iv.approved_at)}` : <span className="muted">not approved</span>}
                          </td>
                          <td className="small nowrap">{dateTime(iv.execution_time)}</td>
                          <td className="small">{iv.outcome ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
            {can("risk.read") && (
              <Card title="Evidence behind this case">
                <details>
                  <summary>Show full evidence panel</summary>
                  <div style={{ marginTop: 10 }}>
                    <EvidencePanel a={a} compact />
                  </div>
                </details>
              </Card>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function useAssignees(roles: string[], enabled: boolean): UserOut[] {
  const [list, setList] = useState<UserOut[]>([]);
  const key = roles.join(",");
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    Promise.all(key.split(",").map((role) => apiGet("/v1/users", { query: { role } })))
      .then((r) => live && setList(r.flat().filter((u) => u.is_active)))
      .catch(() => live && setList([]));
    return () => {
      live = false;
    };
  }, [key, enabled]);
  return list;
}

function ActionForm({ c, onDone }: { c: CaseDetail; onDone: (c: CaseDetail) => void }) {
  const { can } = useAuth();
  const actions = c.available_actions;
  const [action, setAction] = useState<string>(actions[0] ?? "");
  const [justification, setJustification] = useState("");
  const [intervention, setIntervention] = useState(c.assessment.suppressed ? "correct_data" : "filing_reminder");
  const [referral, setReferral] = useState("audit_referral");
  const [materiality, setMateriality] = useState("");
  const [assignee, setAssignee] = useState("");
  const [channel, setChannel] = useState("letter");
  const [findings, setFindings] = useState("");
  const [disposition, setDisposition] = useState("resolved_compliant");
  const [outcome, setOutcome] = useState("");
  const [amount, setAmount] = useState("");
  const act = useAction();

  useEffect(() => {
    if (!actions.includes(action)) setAction(actions[0] ?? "");
  }, [actions, action]);

  const needsAssignee = action === "approve_proposal" || action === "approve_audit" || action === "reassign";
  const assigneeRoles = action === "approve_audit" ? ["audit_manager", "compliance_officer"] : action === "reassign" ? ["compliance_officer", "compliance_manager"] : ["compliance_officer"];
  const assignees = useAssignees(assigneeRoles, needsAssignee && can("users.read"));

  if (actions.length === 0) {
    return (
      <Card title="Next action">
        <div className="stack-sm">
          <ActionResult error={act.error} success={act.success} />
          <p className="muted mb-0">{c.status === "closed" ? "This case is closed." : "No further workflow actions are available to your role at this stage."}</p>
        </div>
      </Card>
    );
  }

  function buildPayload(): Record<string, unknown> | string {
    switch (action) {
      case "submit_proposal":
        return { intervention_type: intervention };
      case "approve_proposal":
      case "approve_audit":
        return assignee ? { assignee_id: assignee } : {};
      case "reassign":
        return assignee ? { assignee_id: assignee } : "Choose an assignee.";
      case "record_contact":
        return { channel };
      case "refer_audit":
        return materiality.trim() ? { intervention_type: referral, materiality: materiality.trim() } : "A materiality statement is required.";
      case "record_audit_findings":
        return findings.trim() ? { findings: findings.trim() } : "Findings are required.";
      case "close": {
        const p: Record<string, unknown> = { disposition };
        if (outcome.trim()) p.outcome = outcome.trim();
        if (amount.trim()) {
          if (!/^\d+(\.\d{1,2})?$/.test(amount.trim())) return "Amount collected must be a non-negative number with up to 2 decimals.";
          p.amount_collected = amount.trim();
        }
        return p;
      }
      default:
        return {};
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reasonOk(justification)) return act.setError("A justification of at least 5 characters is required.");
    const payload = buildPayload();
    if (typeof payload === "string") return act.setError(payload);
    const r = await act.run(
      () => apiPost("/v1/cases/{case_id}/actions", { path: { case_id: c.id }, body: { action, justification: justification.trim(), payload } }),
      (r) => `${ACTION_LABELS[action] ?? action}: done. Case is now ${humanize(r.status).toLowerCase()}.`,
    );
    if (r) {
      setJustification("");
      setMateriality("");
      setFindings("");
      setOutcome("");
      setAmount("");
      onDone(r);
    }
  }

  const interventionOptions = c.assessment.suppressed ? INTERVENTIONS.filter((i) => i === "no_action" || i === "correct_data") : INTERVENTIONS;

  return (
    <Card title="Next action">
      <form onSubmit={submit} className="stack-sm" aria-label="Case workflow action">
        <SelectField label="Action" value={action} onChange={setAction} options={actions.map((x) => ({ value: x, label: ACTION_LABELS[x] ?? humanize(x) }))} />
        {action === "submit_proposal" && (
          <SelectField
            label="Intervention"
            value={intervention}
            onChange={setIntervention}
            options={interventionOptions}
            hint={c.assessment.suppressed ? "Low data confidence: only data correction or no action may be proposed." : "Choose the least intrusive intervention that addresses the indicator."}
          />
        )}
        {action === "refer_audit" && (
          <>
            <SelectField label="Referral type" value={referral} onChange={setReferral} options={REFERRALS} />
            <TextArea label="Materiality statement" value={materiality} onChange={setMateriality} required hint="Why the potential exposure justifies an audit (decided by an audit manager, not you)." rows={2} />
          </>
        )}
        {needsAssignee && (
          <SelectField
            label={action === "reassign" ? "New assignee" : "Assign to (optional)"}
            value={assignee}
            onChange={setAssignee}
            options={assignees.map((u) => ({ value: u.id, label: `${u.full_name} — ${humanize(u.role)}` }))}
            allowEmpty
            emptyLabel={action === "reassign" ? "Choose…" : "Leave unassigned"}
          />
        )}
        {action === "record_contact" && <SelectField label="Contact channel" value={channel} onChange={setChannel} options={CONTACT_CHANNELS} />}
        {action === "record_audit_findings" && <TextArea label="Audit findings" value={findings} onChange={setFindings} required rows={3} />}
        {action === "close" && (
          <div className="form-grid">
            <SelectField label="Disposition" value={disposition} onChange={setDisposition} options={DISPOSITIONS} />
            <TextField label="Amount collected (NGN, optional)" value={amount} onChange={setAmount} inputMode="decimal" placeholder="e.g. 1250000.00" />
            <TextArea className="span-2" label="Outcome (optional)" value={outcome} onChange={setOutcome} rows={2} hint="Defaults to the justification." />
          </div>
        )}
        <ReasonField value={justification} onChange={setJustification} label="Justification (mandatory, audited)" />
        {(action === "approve_proposal" || action === "approve_audit") && (
          <p className="tiny muted mb-0">Four-eyes rule: you cannot approve a proposal or referral you raised yourself.</p>
        )}
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy || !reasonOk(justification)}>
            {act.busy ? "Submitting…" : (ACTION_LABELS[action] ?? "Submit")}
          </button>
        </div>
        <ActionResult error={act.error} success={act.success} />
        {act.error && act.error.includes("HTTP 403") && <Notice tone="info">The server refused this step for your account. Denied attempts are recorded in the audit log.</Notice>}
      </form>
    </Card>
  );
}
