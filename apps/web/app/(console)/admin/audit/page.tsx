"use client";

import type { AuditPage, AuditVerify } from "@ngsirs/contracts";
import { StateMessage } from "@ngsirs/design";
import { useState, type FormEvent } from "react";
import { AsyncBlock, ErrorNotice, Field, Hash, PageHeader, Pager, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

const PAGE_SIZE = 100;

export default function AuditLogPage() {
  return (
    <RequirePermission permission="audit:read" what="the Audit Log">
      <AuditLog />
    </RequirePermission>
  );
}

function AuditLog() {
  const [draft, setDraft] = useState({ event_type: "", actor: "", subject: "" });
  const [filters, setFilters] = useState(draft);
  const [page, setPage] = useState(1);
  const events = useAsync(
    () =>
      unwrap<AuditPage>(
        api.GET("/api/v1/audit-events", {
          params: {
            query: {
              event_type: filters.event_type || undefined,
              actor: filters.actor || undefined,
              subject: filters.subject || undefined,
              page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    [filters, page],
  );
  const verify = useMutation(() => unwrap<AuditVerify>(api.GET("/api/v1/audit-events/verify")));

  function submit(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setFilters(draft);
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Audit Log"
        description="Append-only, hash-chained record of sign-ins, views of sensitive records, decisions, exports (with declared purpose) and configuration changes."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => void verify.run()} disabled={verify.pending}>
            {verify.pending ? "Verifying…" : "Verify hash chain"}
          </button>
        }
      />
      <div aria-live="polite">
        {verify.result &&
          (verify.result.valid ? (
            <StateMessage state="approved" title="Chain verified">
              {verify.result.events} events; head hash <Hash value={verify.result.head_hash} len={24} />
            </StateMessage>
          ) : (
            <StateMessage state="conflict" title="Chain broken">
              Broken at sequence {verify.result.broken_at_seq}: {verify.result.reason}
            </StateMessage>
          ))}
      </div>
      <ErrorNotice error={verify.error} />
      <form className="filters panel" onSubmit={submit} aria-label="Audit filters">
        <Field label="Event type prefix" htmlFor="a-type" hint="e.g. case. or finding.">
          <input id="a-type" type="text" value={draft.event_type} onChange={(e) => setDraft({ ...draft, event_type: e.target.value })} />
        </Field>
        <Field label="Actor" htmlFor="a-actor">
          <input id="a-actor" type="text" value={draft.actor} onChange={(e) => setDraft({ ...draft, actor: e.target.value })} />
        </Field>
        <Field label="Subject" htmlFor="a-subject" hint="Exact, e.g. case:CASE-2026-00001-6B48">
          <input id="a-subject" type="text" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
        </Field>
        <button type="submit" className="btn">
          Filter
        </button>
      </form>
      <Section title="Events">
        <AsyncBlock state={events} what="audit events" empty={(d) => d.items.length === 0}>
          {(d) => (
            <>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                <table className="data">
                  <caption className="ng-visually-hidden">Audit events, newest first</caption>
                  <thead>
                    <tr>
                      <th scope="col" className="num">Seq</th>
                      <th scope="col">When</th>
                      <th scope="col">Event</th>
                      <th scope="col">Actor</th>
                      <th scope="col">Subject</th>
                      <th scope="col">Purpose</th>
                      <th scope="col">Details</th>
                      <th scope="col">Hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((e) => (
                      <tr key={e.seq}>
                        <td className="num">{e.seq}</td>
                        <td className="nowrap">{fmtDateTime(e.occurred_at)}</td>
                        <th scope="row">
                          <code>{e.event_type}</code>
                        </th>
                        <td>{e.actor}</td>
                        <td>
                          <code>{e.subject}</code>
                        </td>
                        <td>{e.purpose ? humanize(e.purpose) : "—"}</td>
                        <td className="small">
                          <code>{e.details ? JSON.stringify(e.details) : "—"}</code>
                        </td>
                        <td>
                          <Hash value={e.event_hash} />
                          {e.trace_id && <div className="small muted">trace {e.trace_id.slice(0, 8)}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pageSize={PAGE_SIZE} total={d.total} onPage={setPage} />
            </>
          )}
        </AsyncBlock>
      </Section>
    </>
  );
}
