"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Badge, Card, ConfidenceBadge, Empty, ErrorBox, Loading, NoAccess, Notice, PageHead, StatusBadge, Tabs, TabPanel, useAsync } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, date, dateTime, humanize, money, num, pct } from "@/lib/format";
import type { Taxpayer360 } from "@/lib/types";

type Tab = "obligations" | "timeline" | "assessments" | "cases";

export default function Taxpayer360Page() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const allowed = can("taxpayers.read");
  const res = useAsync(() => apiGet("/v1/taxpayers/{taxpayer_id}", { path: { taxpayer_id: id } }), [id], allowed);
  const [tab, setTab] = useState<Tab>("obligations");

  if (!allowed) return <NoAccess permission="taxpayers.read" />;
  if (res.error) return <ErrorBox error={res.error} onRetry={res.reload} />;
  if (!res.data) return <Loading label="Loading taxpayer 360…" />;
  const d = res.data;
  const t = d.taxpayer;

  return (
    <>
      <PageHead
        title={t.name}
        description={
          <>
            <Link href="/taxpayers">Taxpayers</Link> / Taxpayer 360 · {humanize(t.taxpayer_type)} · {t.lga ?? "LGA unknown"} · {t.sector ?? "sector unknown"}
          </>
        }
      />
      <div className="stack">
        <Notice tone="info">
          Your access to this record has been logged (actor, role, time). Identifiers are masked{can("taxpayers.read_sensitive") ? " — your role may see partial values and hashes" : ""}. Use this view for the
          purpose of an assigned review only.
        </Notice>
        {d.merged_into_id && (
          <Notice tone="warn" title="Merged record">
            This record was merged into <Link href={`/taxpayers/${d.merged_into_id}`}>another taxpayer</Link>. Obligations were moved to the survivor.
          </Notice>
        )}
        <div className="grid-3">
          <Card title="Profile">
            <dl className="kv">
              <dt>Registration</dt>
              <dd>
                <StatusBadge status={t.registration_status} />
              </dd>
              <dt>Operating status</dt>
              <dd>
                <StatusBadge status={t.operating_status} />
              </dd>
              <dt>Registered on</dt>
              <dd>{date(d.registered_on)}</dd>
              <dt>Closed on</dt>
              <dd>{date(d.closed_on)}</dd>
              <dt>Tax residence</dt>
              <dd>{d.tax_residence}</dd>
              <dt>Roles</dt>
              <dd>{[t.is_employer && "Employer", t.self_employed && "Self-employed"].filter(Boolean).join(", ") || "—"}</dd>
              <dt>Source</dt>
              <dd className="small">{d.source}</dd>
            </dl>
          </Card>
          <Card title="Identity links (masked)">
            {d.identifiers.length === 0 ? (
              <p className="muted">No identifiers linked.</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Type</th>
                    <th scope="col">Value</th>
                    <th scope="col" className="num">
                      Match
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.identifiers.map((i, n) => (
                    <tr key={n}>
                      <td>{i.identifier_type}</td>
                      <td className="mono">
                        {i.value}
                        {i.source_ref && <div className="tiny muted">{i.source_ref}</div>}
                      </td>
                      <td className="num">{pct(i.match_confidence, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Latest risk indicator">
            <dl className="kv">
              <dt>Score</dt>
              <dd>{num(t.latest_score ?? null)} / 100</dd>
              <dt>Confidence</dt>
              <dd>
                <ConfidenceBadge value={t.latest_confidence ?? null} />
              </dd>
            </dl>
            <p className="small muted" style={{ marginTop: 8 }}>
              A score is an indicator for review, not a finding of non-compliance.
            </p>
          </Card>
        </div>

        <Card title="Employment links">
          <EmployerLinks links={d.employer_links} />
        </Card>

        <section className="card">
          <div className="card-body">
            <Tabs<Tab>
              label="Taxpayer records"
              value={tab}
              onChange={setTab}
              tabs={[
                { id: "obligations", label: `Obligations (${d.obligations.length})` },
                { id: "timeline", label: `Filing & payment timeline (${d.returns.length + d.payments.length})` },
                { id: "assessments", label: `Assessments (${d.assessments.length})` },
                { id: "cases", label: `Cases (${d.cases.length})` },
              ]}
            />
            <TabPanel id={tab}>
              {tab === "obligations" && <Obligations d={d} />}
              {tab === "timeline" && <Timeline d={d} />}
              {tab === "assessments" && <Assessments d={d} canRisk={can("risk.read")} />}
              {tab === "cases" && <Cases d={d} canCases={can("cases.read")} />}
            </TabPanel>
          </div>
        </section>
      </div>
    </>
  );
}

function EmployerLinks({ links }: { links: Record<string, unknown>[] }) {
  if (!links.length) return <p className="muted mb-0">No employment relationships recorded.</p>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Relationship</th>
            <th scope="col">Counterparty</th>
            <th scope="col">Start</th>
            <th scope="col">End</th>
          </tr>
        </thead>
        <tbody>
          {links.map((l, i) => {
            const tid = typeof l.taxpayer_id === "string" ? l.taxpayer_id : null;
            const name = typeof l.name === "string" ? l.name : (tid ?? "—");
            return (
              <tr key={i}>
                <td>{humanize(String(l.relationship ?? ""))}</td>
                <td>{tid ? <Link href={`/taxpayers/${tid}`}>{name}</Link> : name}</td>
                <td>{date(l.start_date as string | null)}</td>
                <td>{l.end_date ? date(l.end_date as string) : "current"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Obligations({ d }: { d: Taxpayer360 }) {
  if (!d.obligations.length) return <Empty>No obligations derived. Obligations are generated from approved legal rules for eligible taxpayers.</Empty>;
  const sorted = [...d.obligations].sort((a, b) => b.period.localeCompare(a.period));
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Tax</th>
            <th scope="col">Period</th>
            <th scope="col">Due date</th>
            <th scope="col">Extension</th>
            <th scope="col">Status</th>
            <th scope="col">Legal rule version</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => (
            <tr key={o.id}>
              <td>{o.tax_type}</td>
              <td>{o.period}</td>
              <td>{date(o.due_date)}</td>
              <td>{date(o.extension_until)}</td>
              <td>
                <StatusBadge status={o.status} />
              </td>
              <td>
                <Badge tone="outline" title={`Legal rule ${o.legal_rule_id}`}>
                  v{o.rule_version}
                </Badge>{" "}
                <span className="tiny muted mono">{o.legal_rule_id.slice(0, 8)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ d }: { d: Taxpayer360 }) {
  const events = useMemo(() => {
    const r = d.returns.map((x) => ({ kind: "return" as const, when: x.filing_date, period: x.period, tax: x.tax_type, id: x.id, x }));
    const p = d.payments.map((x) => ({ kind: "payment" as const, when: x.payment_date, period: x.period ?? "unallocated", tax: x.tax_type, id: x.id, x }));
    return [...r, ...p].sort((a, b) => b.when.localeCompare(a.when));
  }, [d]);
  if (!events.length) return <Empty>No returns or payments received from source systems.</Empty>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Event</th>
            <th scope="col">Tax / period</th>
            <th scope="col" className="num">
              Amount
            </th>
            <th scope="col">Details</th>
            <th scope="col">Source (provenance)</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="nowrap">{date(e.when)}</td>
              <td>{e.kind === "return" ? <Badge tone="info">Return filed</Badge> : <Badge tone="accent">Payment</Badge>}</td>
              <td>
                {e.tax} · {e.period}
              </td>
              <td className="num">{e.kind === "return" ? money(e.x.reported_amount) : money(e.x.amount)}</td>
              <td className="small">
                {e.kind === "return" ? (
                  <>
                    Income {money(e.x.reported_income)}
                    {e.x.employee_count !== null ? ` · ${count(e.x.employee_count)} employees` : ""}
                  </>
                ) : (
                  <>Allocation: {humanize(e.x.allocation_status)}</>
                )}
              </td>
              <td className="tiny mono">
                {e.x.source_system}:{e.x.source_record_id}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Assessments({ d, canRisk }: { d: Taxpayer360; canRisk: boolean }) {
  if (!d.assessments.length) return <Empty>No risk assessments.</Empty>;
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Evaluated</th>
            <th scope="col">Tax / period</th>
            <th scope="col" className="num">
              Score
            </th>
            <th scope="col">Confidence</th>
            <th scope="col" className="num">
              Exposure (scenario)
            </th>
            <th scope="col">Reason codes</th>
            <th scope="col">Model</th>
            <th scope="col">State</th>
          </tr>
        </thead>
        <tbody>
          {d.assessments.map((a) => (
            <tr key={a.id}>
              <td className="nowrap">{dateTime(a.evaluation_time)}</td>
              <td>
                {a.tax_type} · {a.period}
              </td>
              <td className="num">{canRisk ? <Link href={`/workbench?assessment=${a.id}`}>{num(a.score)}</Link> : num(a.score)}</td>
              <td>
                <ConfidenceBadge value={a.confidence} />
              </td>
              <td className="num">{money(a.exposure_estimate)}</td>
              <td>
                <div className="chips">
                  {a.reason_codes.map((r) => (
                    <Badge key={r} tone="outline">
                      {r}
                    </Badge>
                  ))}
                </div>
              </td>
              <td>v{a.model_version}</td>
              <td>
                {a.suppressed ? <Badge tone="warn">Low confidence — data verification</Badge> : a.superseded_by_id ? <Badge tone="outline">Superseded</Badge> : <Badge tone="ok">Current</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cases({ d, canCases }: { d: Taxpayer360; canCases: boolean }) {
  if (!d.cases.length) return <Empty>No cases.</Empty>;
  return (
    <table className="data">
      <thead>
        <tr>
          <th scope="col">Reference</th>
          <th scope="col">Status</th>
          <th scope="col">Proposed intervention</th>
          <th scope="col">Disposition</th>
          <th scope="col">SLA due</th>
          <th scope="col">Opened</th>
        </tr>
      </thead>
      <tbody>
        {d.cases.map((c) => (
          <tr key={c.id}>
            <td>{canCases ? <Link href={`/cases/${c.id}`}>{c.reference}</Link> : c.reference}</td>
            <td>
              <StatusBadge status={c.status} />
            </td>
            <td>{humanize(c.proposed_intervention)}</td>
            <td>{humanize(c.disposition)}</td>
            <td>{date(c.sla_due)}</td>
            <td>{date(c.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
