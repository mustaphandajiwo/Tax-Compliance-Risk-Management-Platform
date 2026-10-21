"use client";

import { useState, type FormEvent } from "react";
import { ActionResult, Badge, Card, Empty, ErrorBox, Hash, JsonBlock, Loading, NoAccess, PageHead, Pagination, SelectField, StatusBadge, TextField, useAction, useAsync } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { roleLabel, useAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { Schemas } from "@/lib/api";
import { useUserDirectory, userName } from "@/lib/users";

const LIMIT = 50;

export default function AuditPage() {
  const { can } = useAuth();
  const allowed = can("audit_log.read");
  const users = useUserDirectory(allowed && can("users.read"));
  const [draft, setDraft] = useState({ action: "", outcome: "", resource_type: "", actor_id: "" });
  const [filters, setFilters] = useState(draft);
  const [offset, setOffset] = useState(0);
  const res = useAsync(() => apiGet("/v1/audit-events", { query: { ...filters, limit: LIMIT, offset } }), [JSON.stringify(filters), offset], allowed);
  const verify = useAction();
  const [chain, setChain] = useState<Schemas["ChainVerification"] | null>(null);

  if (!allowed) return <NoAccess permission="audit_log.read" />;

  function submit(e: FormEvent) {
    e.preventDefault();
    setOffset(0);
    setFilters(draft);
  }

  return (
    <>
      <PageHead
        title="Audit log"
        description="Append-only, hash-chained record of every login, view of taxpayer data, decision and denied attempt. Verify the chain to detect tampering."
        actions={
          <button
            type="button"
            className="btn btn-primary"
            disabled={verify.busy}
            onClick={async () => {
              const r = await verify.run(() => apiGet("/v1/audit-events/verify"));
              if (r) setChain(r);
            }}
          >
            {verify.busy ? "Verifying…" : "Verify chain"}
          </button>
        }
      />
      <div className="stack">
        <div aria-live="polite">
          <ActionResult error={verify.error} success={null} />
          {chain && (
            <div className={`notice ${chain.valid ? "notice-ok" : "notice-danger"}`} role={chain.valid ? "status" : "alert"}>
              <div className="notice-title">{chain.valid ? `✓ Chain intact — ${chain.events_checked} events verified` : `✕ Chain broken at sequence ${chain.first_invalid_seq ?? "?"}`}</div>
              {chain.reason && <div>{chain.reason}</div>}
              {chain.head_hash && (
                <div className="small">
                  Head hash: <Hash value={chain.head_hash} />
                </div>
              )}
            </div>
          )}
        </div>
        <Card>
          <form className="filters" onSubmit={submit} aria-label="Audit filters">
            <TextField label="Action prefix" value={draft.action} onChange={(v) => setDraft({ ...draft, action: v })} placeholder="e.g. case. or taxpayer.view" />
            <SelectField label="Outcome" value={draft.outcome} onChange={(v) => setDraft({ ...draft, outcome: v })} options={["success", "denied", "failure"]} allowEmpty emptyLabel="All" />
            <TextField label="Resource type" value={draft.resource_type} onChange={(v) => setDraft({ ...draft, resource_type: v })} placeholder="e.g. case, taxpayer" />
            <SelectField
              label="Actor"
              value={draft.actor_id}
              onChange={(v) => setDraft({ ...draft, actor_id: v })}
              options={[...users.values()].map((u) => ({ value: u.id, label: `${u.full_name} (${roleLabel(u.role)})` }))}
              allowEmpty
              emptyLabel="Anyone"
            />
            <div className="row">
              <button type="submit" className="btn btn-primary">
                Apply
              </button>
            </div>
          </form>
        </Card>
        <Card title={`Events${res.data ? ` (${res.data.total})` : ""}`} pad={false}>
          {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
          {res.loading && !res.data && <Loading />}
          {res.data &&
            (res.data.items.length === 0 ? (
              <Empty>No events match.</Empty>
            ) : (
              <div aria-busy={res.loading}>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col" className="num">
                          Seq
                        </th>
                        <th scope="col">Time (UTC)</th>
                        <th scope="col">Actor</th>
                        <th scope="col">Action</th>
                        <th scope="col">Resource</th>
                        <th scope="col">Outcome</th>
                        <th scope="col">Details</th>
                        <th scope="col">Event hash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {res.data.items.map((e) => (
                        <tr key={e.id}>
                          <td className="num">{e.seq}</td>
                          <td className="nowrap">{dateTime(e.timestamp)}</td>
                          <td className="small">
                            {e.actor_id ? userName(users, e.actor_id) : "system"}
                            {e.actor_role && <div className="tiny muted">{roleLabel(e.actor_role)}</div>}
                          </td>
                          <td>
                            <code>{e.action}</code>
                          </td>
                          <td className="small">
                            {e.resource_type}
                            {e.resource_id && <div className="tiny muted mono">{e.resource_id.slice(0, 8)}</div>}
                          </td>
                          <td>{e.outcome === "denied" ? <Badge tone="danger">Denied</Badge> : <StatusBadge status={e.outcome} />}</td>
                          <td className="small" style={{ maxWidth: 280 }}>
                            {Object.keys(e.details).length ? <JsonBlock value={e.details} summary={summarise(e.details)} /> : "—"}
                          </td>
                          <td className="tiny">
                            <span className="hash" title={`prev ${e.prev_hash}\nthis ${e.event_hash}`}>
                              {e.event_hash.slice(0, 12)}…
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination total={res.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </div>
            ))}
        </Card>
      </div>
    </>
  );
}

function summarise(d: Record<string, unknown>): string {
  const s = Object.entries(d)
    .slice(0, 2)
    .map(([k, v]) => `${k}: ${typeof v === "object" ? "…" : String(v)}`)
    .join(", ");
  return s.length > 60 ? `${s.slice(0, 57)}…` : s;
}
