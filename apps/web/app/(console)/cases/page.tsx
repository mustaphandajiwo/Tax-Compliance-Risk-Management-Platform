"use client";

import type { BatchApproveResult, CaseOut } from "@ngsirs/contracts";
import { StateMessage, StatusBadge } from "@ngsirs/design";
import Link from "next/link";
import { useState } from "react";
import { AsyncBlock, ErrorNotice, Field, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CASE_STAGES, OUTWARD_BLOCKERS } from "@/lib/constants";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";

export default function CasesPage() {
  return (
    <RequirePermission permission="cases:read" what="the Intervention Queue">
      <CaseQueue />
    </RequirePermission>
  );
}

function CaseQueue() {
  const { can, me } = useAuth();
  const [stage, setStage] = useState("");
  const [mine, setMine] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const cases = useAsync(
    () => unwrap<CaseOut[]>(api.GET("/api/v1/cases", { params: { query: { stage: stage || undefined, mine } } })),
    [stage, mine],
  );
  const batch = useMutation(() =>
    unwrap<BatchApproveResult>(api.POST("/api/v1/cases/batch-approve", { body: { case_ids: [...selected], note } })),
  );
  const canApprove = can("cases:approve");

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  const refById = new Map((cases.data ?? []).map((c) => [c.id, c.case_ref]));

  return (
    <>
      <PageHeader
        eyebrow="Case board"
        title="Intervention Queue"
        description="Cases opened from findings. Every case needs manager approval before action; outward taxpayer contact is allowed only when no blocker applies and only through approved templates."
      />
      <form className="filters panel" aria-label="Case filters" onSubmit={(e) => e.preventDefault()}>
        <Field label="Stage" htmlFor="c-stage">
          <select id="c-stage" value={stage} onChange={(e) => setStage(e.target.value)}>
            <option value="">All stages</option>
            {CASE_STAGES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </Field>
        <label className="checkbox">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me ({me?.username})
        </label>
      </form>

      {canApprove && (
        <Section
          title="Batch approval"
          description="Approve several pending cases at once. Ineligible cases (your own, held, or not pending) are skipped with the API's reason, never forced through."
        >
          <form
            className="row-end"
            onSubmit={async (e) => {
              e.preventDefault();
              const r = await batch.run();
              if (r) {
                setSelected(new Set());
                void cases.reload();
              }
            }}
          >
            <Field label="Approval note" htmlFor="b-note" required>
              <input id="b-note" type="text" value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required size={40} />
            </Field>
            <button type="submit" className="btn btn-primary" disabled={selected.size === 0 || note.trim().length < 3 || batch.pending}>
              Approve {selected.size} selected
            </button>
          </form>
          <div aria-live="polite">
            {batch.result && (
              <StateMessage state={batch.result.skipped.length ? "info" : "approved"} title={`Batch result: ${batch.result.approved.length} approved, ${batch.result.skipped.length} skipped`}>
                {batch.result.approved.length > 0 && (
                  <p className="m0">Approved: {batch.result.approved.map((a) => `${a.case_ref}${a.outward_permitted ? "" : " (internal only)"}`).join(", ")}</p>
                )}
                {batch.result.skipped.length > 0 && (
                  <ul className="m0">
                    {batch.result.skipped.map((s) => (
                      <li key={s.case_id}>
                        Skipped {refById.get(s.case_id) ?? s.case_id}: {s.reason}
                      </li>
                    ))}
                  </ul>
                )}
              </StateMessage>
            )}
          </div>
          <ErrorNotice error={batch.error} />
        </Section>
      )}

      <AsyncBlock state={cases} what="cases" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data" data-testid="case-table">
              <caption>{d.length} cases</caption>
              <thead>
                <tr>
                  {canApprove && (
                    <th scope="col">
                      <span className="ng-visually-hidden">Select for batch approval</span>
                    </th>
                  )}
                  <th scope="col">Case</th>
                  <th scope="col">Finding / rule</th>
                  <th scope="col">Employer</th>
                  <th scope="col">LGA · Period</th>
                  <th scope="col">Treatment</th>
                  <th scope="col">Stage</th>
                  <th scope="col">Assigned to</th>
                  <th scope="col">Approval</th>
                  <th scope="col">SLA due</th>
                  <th scope="col">Outward contact</th>
                </tr>
              </thead>
              <tbody>
                {d.map((c) => (
                  <tr key={c.id}>
                    {canApprove && (
                      <td>
                        {c.stage === "pending_approval" && (
                          <input
                            type="checkbox"
                            aria-label={`Select ${c.case_ref}`}
                            checked={selected.has(c.id)}
                            onChange={() => toggle(c.id)}
                          />
                        )}
                      </td>
                    )}
                    <th scope="row">
                      <Link href={`/cases/${c.id}`}>{c.case_ref}</Link>
                      <div className="small muted">Opened {fmtDate(c.created_at)} by {c.created_by}</div>
                    </th>
                    <td>
                      <Link href={`/risks/${c.finding_id}`}>{c.finding_ref}</Link>
                      <div className="small">
                        <code>{c.rule_code}</code>
                      </div>
                    </td>
                    <td>{c.employer_name ?? c.employer_ref ?? "—"}</td>
                    <td className="nowrap">
                      {c.lga ?? "—"} · {c.tax_period ?? "—"}
                    </td>
                    <td>{c.treatment_label ?? humanize(c.treatment)}</td>
                    <td>
                      <StatusBadge status={c.stage} />
                      {c.outcome && <div className="small">{humanize(c.outcome)}</div>}
                    </td>
                    <td>{c.assigned_to ?? <span className="muted">Unassigned</span>}</td>
                    <td>
                      {c.approved_by ? (
                        <span className="small">
                          {c.approved_by}
                          <br />
                          {fmtDateTime(c.approved_at)}
                        </span>
                      ) : c.stage === "rejected" ? (
                        <span className="small">Rejected</span>
                      ) : (
                        <span className="small muted">Awaiting manager</span>
                      )}
                    </td>
                    <td className="nowrap">
                      {fmtDate(c.due_at)} {c.overdue && <StatusBadge status="overdue">Overdue</StatusBadge>}
                    </td>
                    <td>
                      {c.outward_permitted && c.outward_blockers.length === 0 ? (
                        <StatusBadge tone="success">Permitted</StatusBadge>
                      ) : (
                        <span className="small">
                          <StatusBadge tone="neutral">Not permitted</StatusBadge>
                          {c.outward_blockers.length > 0 && <div>{c.outward_blockers.map((b) => OUTWARD_BLOCKERS[b] ?? humanize(b)).join("; ")}</div>}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncBlock>
    </>
  );
}
