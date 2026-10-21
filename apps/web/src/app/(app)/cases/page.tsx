"use client";

import { useState } from "react";
import { CaseTable } from "@/components/CaseTable";
import { Card, ErrorBox, Loading, NoAccess, PageHead, Pagination, SelectField, useAsync } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanize } from "@/lib/format";
import { CASE_STATUSES } from "@/lib/reference";
import { useUserDirectory } from "@/lib/users";

const LIMIT = 25;

export default function CasesPage() {
  const { can } = useAuth();
  const allowed = can("cases.read");
  const users = useUserDirectory(allowed && can("users.read"));
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(false);
  const [breached, setBreached] = useState(false);
  const [offset, setOffset] = useState(0);

  const res = useAsync(
    () =>
      apiGet("/v1/cases", {
        query: { status, assignee: mine ? "me" : undefined, sla_breached: breached ? true : undefined, limit: LIMIT, offset },
      }),
    [status, mine, breached, offset],
    allowed,
  );

  if (!allowed) return <NoAccess permission="cases.read" />;

  return (
    <>
      <PageHead
        title="Cases"
        description="Each case follows a governed workflow: proposal → second-person approval → work → closure. Every step needs a justification and is audited."
      />
      <div className="stack">
        <Card>
          <div className="filters" role="group" aria-label="Case filters">
            <SelectField
              label="Stage"
              value={status}
              onChange={(v) => {
                setStatus(v);
                setOffset(0);
              }}
              options={CASE_STATUSES.map((s) => ({ value: s, label: humanize(s) }))}
              allowEmpty
              emptyLabel="All stages"
            />
            <label className="check">
              <input
                type="checkbox"
                checked={mine}
                onChange={(e) => {
                  setMine(e.target.checked);
                  setOffset(0);
                }}
              />
              Assigned to me
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={breached}
                onChange={(e) => {
                  setBreached(e.target.checked);
                  setOffset(0);
                }}
              />
              SLA breached
            </label>
          </div>
        </Card>
        <Card pad={false} title={`Cases${res.data ? ` (${res.data.total})` : ""}`}>
          {res.error && (
            <div className="card-body">
              <ErrorBox error={res.error} onRetry={res.reload} />
            </div>
          )}
          {res.loading && !res.data && <Loading />}
          {res.data && (
            <div aria-busy={res.loading} aria-live="polite">
              <CaseTable items={res.data.items} users={users} />
              <Pagination total={res.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
