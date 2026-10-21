"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import {
  ActionResult,
  Badge,
  Card,
  Empty,
  ErrorBox,
  Hash,
  Loading,
  NoAccess,
  Notice,
  PageHead,
  Pagination,
  ReasonField,
  reasonOk,
  SelectField,
  StatusBadge,
  Tabs,
  TabPanel,
  TextArea,
  TextField,
  useAction,
  useAsync,
} from "@/components/ui";
import { apiGet, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canonicalJson, sha256Hex, uuid } from "@/lib/canonical";
import { count, date, dateTime, humanize, pct } from "@/lib/format";
import type { DataQualitySummary, ImportOut, MergeCandidateOut, Page, QuarantineItem } from "@/lib/types";

type Tab = "summary" | "imports" | "quarantine" | "merges" | "upload";

export default function DataQualityPage() {
  const { can, canAny } = useAuth();
  const allowed = canAny("imports.read", "data_quality.review");
  const tabs: { id: Tab; label: string }[] = [
    ...(can("imports.read") ? [{ id: "summary" as const, label: "Summary" }, { id: "imports" as const, label: "Import batches" }] : []),
    ...(can("data_quality.review") ? [{ id: "quarantine" as const, label: "Quarantine" }, { id: "merges" as const, label: "Merge candidates" }] : []),
    ...(can("imports.create") ? [{ id: "upload" as const, label: "Upload import" }] : []),
  ];
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? "summary");

  if (!allowed) return <NoAccess permission="imports.read" />;

  return (
    <>
      <PageHead
        title="Data quality"
        description="Connector freshness, ingestion outcomes, quarantined records and identity resolution. Risk confidence depends on what you see here."
      />
      <Tabs<Tab> label="Data quality sections" tabs={tabs} value={tab} onChange={setTab} />
      <TabPanel id={tab}>
        {tab === "summary" && <Summary onGo={setTab} />}
        {tab === "imports" && <Imports />}
        {tab === "quarantine" && <Quarantine />}
        {tab === "merges" && <Merges />}
        {tab === "upload" && <Upload />}
      </TabPanel>
    </>
  );
}

function Summary({ onGo }: { onGo: (t: Tab) => void }) {
  const { can } = useAuth();
  const res = useAsync(async () => (await apiGet("/v1/data-quality/summary")) as unknown as DataQualitySummary, []);
  if (res.error) return <ErrorBox error={res.error} onRetry={res.reload} />;
  if (!res.data) return <Loading />;
  const d = res.data;
  const stale = d.connectors.filter((c) => c.stale);
  const totalRecords = Object.values(d.record_status_counts).reduce((a, b) => a + b, 0);
  return (
    <div className="stack">
      <div className="grid-kpi">
        <Tile label="Stale feeds" value={count(stale.length)} sub={`of ${d.connectors.length} connectors · stale after ${d.stale_after_days} days`} tone={stale.length ? "danger" : "ok"} />
        <Tile label="Open quarantine" value={count(d.quarantined_open)} sub="records awaiting review" tone={d.quarantined_open ? "warn" : "ok"} action={can("data_quality.review") ? () => onGo("quarantine") : undefined} />
        <Tile label="Unreconciled batches" value={count(d.unreconciled_batches)} sub="control totals not matched" tone={d.unreconciled_batches ? "danger" : "ok"} />
        <Tile
          label="Merge candidates"
          value={count(Object.values(d.merge_candidates).reduce((a, b) => a + b, 0))}
          sub={Object.entries(d.merge_candidates).map(([k, v]) => `${humanize(k)} ${v}`).join(" · ") || "none"}
          tone="info"
          action={can("data_quality.review") ? () => onGo("merges") : undefined}
        />
      </div>
      <Card title="Connectors" pad={false}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Dataset</th>
                <th scope="col">Source system</th>
                <th scope="col">Last extracted</th>
                <th scope="col" className="num">
                  Age
                </th>
                <th scope="col">Freshness</th>
                <th scope="col">Last batch</th>
              </tr>
            </thead>
            <tbody>
              {d.connectors.map((c) => (
                <tr key={`${c.dataset}-${c.source_system}`}>
                  <td>{humanize(c.dataset)}</td>
                  <td className="mono">{c.source_system}</td>
                  <td>{date(c.last_extracted_at)}</td>
                  <td className="num">{c.age_days === null ? "—" : `${c.age_days} d`}</td>
                  <td>{c.stale ? <Badge tone="danger">Stale</Badge> : <Badge tone="ok">Fresh</Badge>}</td>
                  <td>
                    <StatusBadge status={c.last_batch_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Record outcomes (all batches)">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Records
                </th>
                <th scope="col" className="num">
                  Share
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.record_status_counts).map(([k, v]) => (
                <tr key={k}>
                  <td>
                    <StatusBadge status={k} />
                  </td>
                  <td className="num">{count(v)}</td>
                  <td className="num">{pct(totalRecords ? v / totalRecords : null, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function Tile({ label, value, sub, tone, action }: { label: string; value: string; sub: string; tone: "ok" | "warn" | "danger" | "info"; action?: () => void }) {
  return (
    <section className="card kpi">
      <div className="kpi-label">
        <span>{label}</span>
        <Badge tone={tone}>{tone === "ok" ? "OK" : tone === "info" ? "Review" : "Attention"}</Badge>
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-frac">{sub}</div>
      {action && (
        <button type="button" className="btn btn-sm btn-ghost" onClick={action} style={{ alignSelf: "flex-start" }}>
          Review
        </button>
      )}
    </section>
  );
}

const IMPORT_LIMIT = 20;

function Imports() {
  const [dataset, setDataset] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<{ batch: ImportOut; status: string } | null>(null);
  const res = useAsync(() => apiGet("/v1/imports", { query: { dataset, limit: IMPORT_LIMIT, offset } }), [dataset, offset]);
  return (
    <div className="stack">
      <Card>
        <div className="filters">
          <SelectField
            label="Dataset"
            value={dataset}
            onChange={(v) => {
              setDataset(v);
              setOffset(0);
            }}
            options={["taxpayers", "employments", "returns", "payments"]}
            allowEmpty
            emptyLabel="All datasets"
          />
        </div>
      </Card>
      <Card title="Import batches" pad={false}>
        {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
        {res.loading && !res.data && <Loading />}
        {res.data && (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Dataset</th>
                    <th scope="col">Source</th>
                    <th scope="col">Extracted</th>
                    <th scope="col">Status</th>
                    <th scope="col" className="num">
                      Total
                    </th>
                    <th scope="col" className="num">
                      Accepted
                    </th>
                    <th scope="col" className="num">
                      Rejected
                    </th>
                    <th scope="col" className="num">
                      Duplicate
                    </th>
                    <th scope="col" className="num">
                      Quarantined
                    </th>
                    <th scope="col">Reconciliation</th>
                    <th scope="col">Checksum</th>
                  </tr>
                </thead>
                <tbody>
                  {res.data.items.map((b) => (
                    <tr key={b.id} className={open?.batch.id === b.id ? "selected" : undefined}>
                      <td>{humanize(b.dataset)}</td>
                      <td className="mono small">{b.source_system}</td>
                      <td className="nowrap">{date(b.extracted_at)}</td>
                      <td>
                        <StatusBadge status={b.status} />
                        {b.error && <div className="tiny" style={{ color: "var(--danger)" }}>{b.error}</div>}
                      </td>
                      <td className="num">{count(b.total)}</td>
                      <td className="num">{count(b.accepted)}</td>
                      <td className="num">
                        {b.rejected > 0 ? (
                          <button type="button" className="row-button" onClick={() => setOpen({ batch: b, status: "rejected" })} aria-label={`Show ${b.rejected} rejected records`}>
                            {count(b.rejected)}
                          </button>
                        ) : (
                          0
                        )}
                      </td>
                      <td className="num">{count(b.duplicate)}</td>
                      <td className="num">
                        {b.quarantined > 0 ? (
                          <button type="button" className="row-button" onClick={() => setOpen({ batch: b, status: "quarantined" })} aria-label={`Show ${b.quarantined} quarantined records`}>
                            {count(b.quarantined)}
                          </button>
                        ) : (
                          0
                        )}
                      </td>
                      <td>
                        <StatusBadge status={b.reconciliation_status} />
                      </td>
                      <td className="tiny">
                        <span className="hash" title={b.checksum}>
                          {b.checksum.slice(0, 12)}…
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={res.data.total} limit={IMPORT_LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
      {open && <BatchRecords key={`${open.batch.id}-${open.status}`} batch={open.batch} initialStatus={open.status} onClose={() => setOpen(null)} />}
    </div>
  );
}

function BatchRecords({ batch, initialStatus, onClose }: { batch: ImportOut; initialStatus: string; onClose: () => void }) {
  const [status, setStatus] = useState(initialStatus);
  const res = useAsync(() => apiGet("/v1/imports/{batch_id}/records", { path: { batch_id: batch.id }, query: { status, limit: 100 } }), [batch.id, status]);
  return (
    <Card
      title={`Records in ${humanize(batch.dataset)} batch ${batch.id.slice(0, 8)} (${batch.source_system})`}
      actions={
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Close
        </button>
      }
    >
      <div className="filters" style={{ marginBottom: 10 }}>
        <SelectField label="Record status" value={status} onChange={setStatus} options={["rejected", "quarantined", "duplicate", "accepted"]} />
      </div>
      {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
      {res.loading && !res.data && <Loading />}
      {res.data && (res.data.items.length === 0 ? <Empty>No {status} records in this batch.</Empty> : <RecordsTable items={res.data.items} />)}
    </Card>
  );
}

function RecordsTable({ items }: { items: { id: string; row_number: number; source_record_id: string | null; status: string; errors: Record<string, unknown>[]; resolution: string | null }[] }) {
  return (
    <div className="table-wrap" aria-live="polite">
      <table className="data">
        <thead>
          <tr>
            <th scope="col" className="num">
              Row
            </th>
            <th scope="col">Source record</th>
            <th scope="col">Status</th>
            <th scope="col">Errors</th>
            <th scope="col">Resolution</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td className="num">{r.row_number}</td>
              <td className="mono small">{r.source_record_id ?? "—"}</td>
              <td>
                <StatusBadge status={r.status} />
              </td>
              <td className="small">
                <ErrorList errors={r.errors} />
              </td>
              <td className="small">{r.resolution ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ErrorList({ errors }: { errors: Record<string, unknown>[] }) {
  if (!errors.length) return <span className="muted">—</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: 16 }}>
      {errors.map((e, i) => (
        <li key={i}>
          {e.field ? <code>{String(e.field)}</code> : null} {String(e.message ?? e.msg ?? JSON.stringify(e))}
        </li>
      ))}
    </ul>
  );
}

function Quarantine() {
  const [offset, setOffset] = useState(0);
  const res = useAsync(async () => (await apiGet("/v1/data-quality/quarantine", { query: { limit: 50, offset } })) as unknown as Page<QuarantineItem>, [offset]);
  const act = useAction();
  const [busyId, setBusyId] = useState<string | null>(null);

  async function reprocess(id: string) {
    setBusyId(id);
    const r = await act.run(
      () => apiPost("/v1/import-records/{record_id}/reprocess", { path: { record_id: id } }),
      (r) => `Record reprocessed — new status: ${humanize(r.status)}${r.errors.length ? ` (${r.errors.map((e) => String((e as { message?: string }).message ?? "")).join("; ")})` : ""}.`,
    );
    setBusyId(null);
    if (r) res.reload();
  }

  return (
    <Card title={`Quarantined records${res.data ? ` (${res.data.total})` : ""}`} pad={false}>
      <div className="card-body">
        <p className="small muted mb-0">
          Quarantined records passed validation but could not be linked (e.g. TIN not yet in the taxpayer master). Reprocess after the master data is corrected.
        </p>
        <ActionResult error={act.error} success={act.success} />
      </div>
      {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
      {res.loading && !res.data && <Loading />}
      {res.data &&
        (res.data.items.length === 0 ? (
          <Empty>Nothing in quarantine.</Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Dataset</th>
                    <th scope="col">Source</th>
                    <th scope="col" className="num">
                      Row
                    </th>
                    <th scope="col">Source record</th>
                    <th scope="col">Errors</th>
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {res.data.items.map((q) => (
                    <tr key={q.id}>
                      <td>{humanize(q.dataset)}</td>
                      <td className="mono small">{q.source_system}</td>
                      <td className="num">{q.row_number}</td>
                      <td className="mono small">{q.source_record_id ?? "—"}</td>
                      <td className="small">
                        <ErrorList errors={q.errors as Record<string, unknown>[]} />
                      </td>
                      <td>
                        <button type="button" className="btn btn-sm" disabled={busyId === q.id} onClick={() => reprocess(q.id)}>
                          {busyId === q.id ? "Reprocessing…" : "Reprocess"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={res.data.total} limit={50} offset={offset} onChange={setOffset} />
          </>
        ))}
    </Card>
  );
}

const MERGE_ACTIONS: Record<string, ("propose" | "approve" | "reject" | "rollback")[]> = {
  candidate: ["propose", "reject"],
  proposed: ["approve", "reject"],
  merged: ["rollback"],
};

function Merges() {
  const { can, me } = useAuth();
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<MergeCandidateOut | null>(null);
  const res = useAsync(() => apiGet("/v1/merge-candidates", { query: { status, limit: 100 } }), [status]);
  const scan = useAction();

  return (
    <div className="stack">
      <Card
        title="Identity resolution"
        actions={
          can("merges.propose") ? (
            <button type="button" className="btn btn-sm" disabled={scan.busy} onClick={() => scan.run(() => apiPost("/v1/merge-candidates/scan"), (r) => `Scan complete: ${JSON.stringify(r)}`).then(() => res.reload())}>
              {scan.busy ? "Scanning…" : "Scan for candidates"}
            </button>
          ) : undefined
        }
      >
        <p className="small mb-0">
          Merges follow four-eyes control: one steward proposes, a <strong>different</strong> steward approves. Merges can be rolled back. Unresolved likely duplicates suppress risk
          scoring for the affected taxpayers.
        </p>
        <div className="filters" style={{ marginTop: 10 }}>
          <SelectField label="Status" value={status} onChange={setStatus} options={["candidate", "proposed", "merged", "rejected", "rolled_back"]} allowEmpty emptyLabel="All" />
        </div>
        <ActionResult error={scan.error} success={scan.success} />
      </Card>
      <div className="split">
        <Card title={`Candidates${res.data ? ` (${res.data.total})` : ""}`} pad={false}>
          {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
          {res.loading && !res.data && <Loading />}
          {res.data &&
            (res.data.items.length === 0 ? (
              <Empty>No merge candidates.</Empty>
            ) : (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Survivor ← duplicate</th>
                      <th scope="col" className="num">
                        Confidence
                      </th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.data.items.map((m) => (
                      <tr key={m.id} className={selected?.id === m.id ? "selected" : undefined}>
                        <td>
                          <button type="button" className="row-button" onClick={() => setSelected(m)}>
                            {m.survivor_name ?? m.survivor_id.slice(0, 8)}
                          </button>
                          <div className="small muted">← {m.duplicate_name ?? m.duplicate_id.slice(0, 8)}</div>
                        </td>
                        <td className="num">{pct(m.confidence, 0)}</td>
                        <td>
                          <StatusBadge status={m.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
        </Card>
        {selected ? (
          <MergeDecision
            key={selected.id}
            m={selected}
            meId={me?.id}
            onDone={(m) => {
              // the decision response may omit display names; keep the ones we already have
              setSelected({ ...m, survivor_name: m.survivor_name ?? selected.survivor_name, duplicate_name: m.duplicate_name ?? selected.duplicate_name });
              res.reload();
            }}
          />
        ) : (
          <Card title="Decision">
            <Empty>Select a candidate to compare and decide.</Empty>
          </Card>
        )}
      </div>
    </div>
  );
}

function MergeDecision({ m, meId, onDone }: { m: MergeCandidateOut; meId?: string; onDone: (m: MergeCandidateOut) => void }) {
  const { can } = useAuth();
  const options = (MERGE_ACTIONS[m.status] ?? []).filter((d) => (d === "approve" || d === "rollback" ? can("merges.approve") : can("merges.propose")));
  const [chosen, setDecision] = useState(options[0] ?? "propose");
  const decision = options.includes(chosen) ? chosen : (options[0] ?? chosen);
  const [reason, setReason] = useState("");
  const act = useAction();
  const ownProposal = m.status === "proposed" && m.proposed_by === meId;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reasonOk(reason)) return act.setError("A reason of at least 5 characters is required.");
    const r = await act.run(
      () => apiPost("/v1/merge-candidates/{candidate_id}/decision", { path: { candidate_id: m.id }, body: { decision, reason: reason.trim() } }),
      (r) => `Decision recorded — candidate is now ${humanize(r.status).toLowerCase()}.`,
    );
    if (r) {
      setReason("");
      onDone(r);
    }
  }

  return (
    <Card title="Decision">
      <div className="stack-sm">
        <dl className="kv">
          <dt>Survivor</dt>
          <dd>
            <Link href={`/taxpayers/${m.survivor_id}`}>{m.survivor_name ?? m.survivor_id}</Link>
          </dd>
          <dt>Duplicate</dt>
          <dd>
            <Link href={`/taxpayers/${m.duplicate_id}`}>{m.duplicate_name ?? m.duplicate_id}</Link>
          </dd>
          <dt>Match confidence</dt>
          <dd>{pct(m.confidence, 0)}</dd>
          <dt>Evidence</dt>
          <dd>
            <div className="chips">
              {m.reasons.map((r) => (
                <Badge key={r} tone="outline">
                  {humanize(r)}
                </Badge>
              ))}
            </div>
          </dd>
          <dt>Status</dt>
          <dd>
            <StatusBadge status={m.status} />
          </dd>
          <dt>Decided</dt>
          <dd>{dateTime(m.decided_at)}</dd>
          <dt>Last reason</dt>
          <dd>{m.decision_reason ?? "—"}</dd>
        </dl>
        {ownProposal && (
          <Notice tone="info" title="Four-eyes control">
            You proposed this merge. Another data steward must approve it.
          </Notice>
        )}
        {options.length > 0 ? (
          <form onSubmit={submit} className="stack-sm" aria-label="Merge decision">
            <fieldset>
              <legend>Decision</legend>
              <div className="radio-row">
                {options.map((d) => (
                  <label key={d}>
                    <input type="radio" name="merge-decision" value={d} checked={decision === d} onChange={() => setDecision(d)} />
                    {humanize(d)}
                  </label>
                ))}
              </div>
            </fieldset>
            <ReasonField value={reason} onChange={setReason} />
            <div className="row">
              <button type="submit" className={`btn ${decision === "reject" || decision === "rollback" ? "btn-danger" : "btn-primary"}`} disabled={act.busy || !reasonOk(reason)}>
                {act.busy ? "Recording…" : `Record: ${humanize(decision)}`}
              </button>
            </div>
          </form>
        ) : (
          <p className="small muted mb-0">No decisions available for this status.</p>
        )}
        <ActionResult error={act.error} success={act.success} />
      </div>
    </Card>
  );
}

const SAMPLE: Record<string, string> = {
  taxpayers: JSON.stringify(
    [{ source_record_id: "UI-TP-0001", taxpayer_type: "business", name: "Example Trading Ltd", tin: "20000001", tax_residence: "NI", lga: "Bida", sector: "Retail", is_employer: true }],
    null,
    2,
  ),
  employments: JSON.stringify([{ source_record_id: "UI-EMP-0001", employer_tin: "20000001", employee_tin: "30000001", start_date: "2026-01-01" }], null, 2),
  returns: JSON.stringify(
    [{ source_record_id: "UI-RET-0001", tin: "20000001", tax_type: "PAYE", period: "2026-09", filing_date: "2026-10-08", reported_income: "1500000.00", reported_amount: "105000.00", employee_count: 4 }],
    null,
    2,
  ),
  payments: JSON.stringify([{ source_record_id: "UI-PAY-0001", tin: "20000001", tax_type: "PAYE", period: "2026-09", amount: "105000.00", payment_date: "2026-10-09" }], null, 2),
};

function Upload() {
  const [dataset, setDataset] = useState<"taxpayers" | "employments" | "returns" | "payments">("returns");
  const [sourceSystem, setSourceSystem] = useState("NG-PAYE-PORTAL");
  const [schemaVersion, setSchemaVersion] = useState("1.0");
  const [extractedAt, setExtractedAt] = useState(new Date().toISOString().slice(0, 10));
  const [text, setText] = useState(SAMPLE.returns ?? "[]");
  const [idem, setIdem] = useState(() => uuid());
  const [checksum, setChecksum] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const act = useAction();
  const [result, setResult] = useState<ImportOut | null>(null);

  function parse(): unknown[] | null {
    try {
      const v: unknown = JSON.parse(text);
      if (!Array.isArray(v)) throw new Error("The payload must be a JSON array of records.");
      if (!v.every((x) => x && typeof x === "object" && !Array.isArray(x))) throw new Error("Every array item must be a JSON object.");
      setParseError(null);
      return v;
    } catch (e) {
      setParseError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }

  async function computeChecksum(): Promise<string | null> {
    const recs = parse();
    if (!recs) return null;
    const c = await sha256Hex(canonicalJson(recs));
    setChecksum(c);
    return c;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const recs = parse();
    if (!recs) return;
    const c = await computeChecksum();
    if (!c) return;
    const r = await act.run(
      () =>
        apiPost("/v1/imports", {
          body: { dataset, source_system: sourceSystem.trim(), schema_version: schemaVersion.trim() || "1.0", idempotency_key: idem, checksum: c, extracted_at: extractedAt || null, records: recs as Record<string, unknown>[] },
        }),
      (b) => `Batch ${b.id.slice(0, 8)} registered — status ${humanize(b.status)}: ${b.accepted} accepted, ${b.rejected} rejected, ${b.duplicate} duplicate, ${b.quarantined} quarantined.`,
    );
    if (r) setResult(r);
  }

  async function onFile(f: File | undefined) {
    if (!f) return;
    setText(await f.text());
    setChecksum(null);
  }

  return (
    <div className="split">
      <Card title="Upload an import batch">
        <form onSubmit={submit} className="stack-sm" aria-label="Upload import">
          <div className="form-grid">
            <SelectField
              label="Dataset"
              value={dataset}
              onChange={(v) => {
                const d = v as typeof dataset;
                setDataset(d);
                setText(SAMPLE[d] ?? "[]");
                setChecksum(null);
              }}
              options={["taxpayers", "employments", "returns", "payments"]}
            />
            <TextField label="Source system" value={sourceSystem} onChange={setSourceSystem} required hint="e.g. NG-PAYE-PORTAL, NG-COLLECTIONS, NG-SIRS-REGISTER" />
            <TextField label="Schema version" value={schemaVersion} onChange={setSchemaVersion} />
            <TextField label="Extracted at" type="date" value={extractedAt} onChange={setExtractedAt} hint="Drives feed freshness." />
          </div>
          <div className="field">
            <label htmlFor="import-file">Load from file (optional)</label>
            <input id="import-file" type="file" accept="application/json,.json" onChange={(e) => onFile(e.target.files?.[0])} />
          </div>
          <TextArea
            label="Records (JSON array)"
            value={text}
            onChange={(v) => {
              setText(v);
              setChecksum(null);
            }}
            code
            rows={12}
            hint='Send decimals as strings (e.g. "105000.00") for exact money values.'
          />
          {parseError && (
            <p role="alert" className="small" style={{ color: "var(--danger)" }}>
              {parseError}
            </p>
          )}
          <dl className="kv">
            <dt>Idempotency key</dt>
            <dd className="row">
              <span className="mono small">{idem}</span>
              <button type="button" className="btn btn-sm" onClick={() => setIdem(uuid())}>
                New key
              </button>
            </dd>
            <dt>Checksum (SHA-256)</dt>
            <dd>{checksum ? <Hash value={checksum} label="Checksum" /> : <span className="muted small">computed on submit</span>}</dd>
          </dl>
          <div className="row">
            <button type="button" className="btn" onClick={() => void computeChecksum()}>
              Compute checksum
            </button>
            <button type="submit" className="btn btn-primary" disabled={act.busy}>
              {act.busy ? "Uploading…" : "Upload batch"}
            </button>
          </div>
          <ActionResult error={act.error} success={act.success} />
        </form>
      </Card>
      <div className="stack">
        <Card title="How the checksum is computed">
          <p className="small">
            SHA-256 (hex) of the canonical JSON of the records array: keys sorted recursively, separators <code>,</code> and <code>:</code> with no spaces, and non-ASCII characters
            escaped as <code>\uXXXX</code> — identical to Python&apos;s <code>json.dumps(records, sort_keys=True, separators=(&quot;,&quot;, &quot;:&quot;))</code>.
          </p>
          <p className="small mb-0">
            Re-sending the same idempotency key with the same checksum returns the original batch; a different checksum under the same key is rejected (HTTP 409).
          </p>
        </Card>
        {result && (
          <Card title={`Batch ${result.id.slice(0, 8)}`}>
            <dl className="kv">
              <dt>Status</dt>
              <dd>
                <StatusBadge status={result.status} />
              </dd>
              <dt>Total</dt>
              <dd>{result.total}</dd>
              <dt>Accepted / rejected</dt>
              <dd>
                {result.accepted} / {result.rejected}
              </dd>
              <dt>Duplicate / quarantined</dt>
              <dd>
                {result.duplicate} / {result.quarantined}
              </dd>
              <dt>Reconciliation</dt>
              <dd>
                <StatusBadge status={result.reconciliation_status} />
              </dd>
            </dl>
            {(result.rejected > 0 || result.quarantined > 0) && <BatchRecords batch={result} initialStatus={result.rejected > 0 ? "rejected" : "quarantined"} onClose={() => setResult(null)} />}
          </Card>
        )}
      </div>
    </div>
  );
}
