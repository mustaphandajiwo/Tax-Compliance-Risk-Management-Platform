"use client";

import Link from "next/link";
import { Badge, Empty, StatusBadge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { date, humanize } from "@/lib/format";
import type { CaseSummary, UserOut } from "@/lib/types";
import { userName } from "@/lib/users";

export function isSlaBreached(c: { sla_due: string; status: string }, today = new Date().toISOString().slice(0, 10)): boolean {
  return c.status !== "closed" && c.sla_due < today;
}

export function CaseTable({ items, users }: { items: CaseSummary[]; users: Map<string, UserOut> }) {
  const { me } = useAuth();
  if (!items.length) return <Empty>No cases match these filters.</Empty>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Reference</th>
            <th scope="col">Taxpayer</th>
            <th scope="col">Stage</th>
            <th scope="col">Intervention</th>
            <th scope="col">Assignee</th>
            <th scope="col">SLA due</th>
            <th scope="col">Disposition</th>
            <th scope="col">Opened</th>
          </tr>
        </thead>
        <tbody>
          {items.map((c) => {
            const breached = isSlaBreached(c);
            return (
              <tr key={c.id}>
                <td>
                  <Link href={`/cases/${c.id}`}>{c.reference}</Link>
                </td>
                <td>{c.taxpayer_name ?? "—"}</td>
                <td>
                  <StatusBadge status={c.status} />
                </td>
                <td>{humanize(c.proposed_intervention)}</td>
                <td className="small">{userName(users, c.assignee_id, me?.id, me?.full_name)}</td>
                <td className="nowrap">
                  {date(c.sla_due)} {breached && <Badge tone="danger">SLA breached</Badge>}
                </td>
                <td>{humanize(c.disposition)}</td>
                <td className="nowrap">{date(c.created_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
