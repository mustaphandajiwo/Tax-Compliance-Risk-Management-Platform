"use client";

import type {
  ConnectorDetail,
  ConnectorItem,
  ConnectorRunItem,
  DataSource,
  FeedTemplate,
  IdentityDecisionCode,
  IdentityMatchItem,
  ImportBatchOut,
  ImportRowsPage,
  QuarantineItem,
  QuarantineResolutionCode,
} from "@ngsirs/contracts";
import { StateMessage, StatusBadge } from "@ngsirs/design";
import { useState, type FormEvent } from "react";
import { Tabs } from "@/components/Tabs";
import { AsyncBlock, ErrorNotice, Field, Hash, JsonView, KeyValues, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, idempotencyKey, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation, useReference } from "@/lib/hooks";
import { fmtConfidence, fmtDateTime, fmtPct, humanize } from "@/lib/format";

export default function ImportsPage() {
  return (
    <RequirePermission permission={["imports:read", "quality:read"]} what="Data Imports">
      <DataOperations />
    </RequirePermission>
  );
}

function DataOperations() {
  const { can } = useAuth();
  const tabs = [
    ...(can("imports:read") ? [{ id: "batches", label: "Import batches" }] : []),
    ...(can("quality:read")
      ? [
          { id: "quarantine", label: "Quarantine queue" },
          { id: "identity", label: "Identity match review" },
        ]
      : []),
    ...(can("imports:read")
      ? [
          { id: "connectors", label: "System connectors" },
          { id: "sources", label: "Data sources & freshness" },
          { id: "templates", label: "Feed templates" },
        ]
      : []),
  ];
  const [tab, setTab] = useState(tabs[0]?.id ?? "quarantine");
  return (
    <>
      <PageHeader
        eyebrow="Data operations"
        title="Data Imports"
        description="Load signed, tenant-scoped source extracts; validate them against feed templates; commit or roll back; and resolve quarantined records and uncertain identity matches. Invalid or ambiguous data routes here, never to enforcement."
      />
      <Tabs tabs={tabs} active={tab} onChange={setTab} label="Data operations sections">
        {tab === "batches" && <Batches />}
        {tab === "quarantine" && <Quarantine />}
        {tab === "identity" && <IdentityQueue />}
        {tab === "connectors" && <Connectors />}
        {tab === "sources" && <Sources />}
        {tab === "templates" && <Templates />}
      </Tabs>
    </>
  );
}

// --- batches & upload -------------------------------------------------------------------------

function Batches() {
  const { can } = useAuth();
  const batches = useAsync(() => unwrap<ImportBatchOut[]>(api.GET("/api/v1/imports")), []);
  const [selected, setSelected] = useState<ImportBatchOut | null>(null);
  return (
    <>
      {can("imports:create") && (
        <UploadForm
          onCreated={(b) => {
            setSelected(b);
            void batches.reload();
          }}
        />
      )}
      {selected && (
        <BatchDetail
          batch={selected}
          onChanged={(b) => {
            setSelected(b);
            void batches.reload();
          }}
        />
      )}
      <Section title="Import batches">
        <AsyncBlock state={batches} what="import batches" empty={(d) => d.length === 0}>
          {(d) => (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data" data-testid="batch-table">
                <caption className="ng-visually-hidden">Import batches, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">File</th>
                    <th scope="col">Source · feed</th>
                    <th scope="col">Extracted</th>
                    <th scope="col">Coverage</th>
                    <th scope="col">QA status</th>
                    <th scope="col" className="num">Rows</th>
                    <th scope="col" className="num">Accepted</th>
                    <th scope="col" className="num">Quarantined</th>
                    <th scope="col" className="num">Rejected</th>
                    <th scope="col">
                      <span className="ng-visually-hidden">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.map((b) => (
                    <tr key={b.id}>
                      <td>{b.seq}</td>
                      <th scope="row">{b.file_name}</th>
                      <td>
                        {b.source ?? "—"}
                        <div className="small muted">{b.feed_type}</div>
                      </td>
                      <td className="nowrap">{fmtDateTime(b.extracted_at)}</td>
                      <td className="nowrap">
                        {String(b.coverage.from ?? "—")} – {String(b.coverage.to ?? "—")}
                        {b.coverage.lga ? ` · ${String(b.coverage.lga)}` : ""}
                      </td>
                      <td>
                        <StatusBadge status={b.qa_status} />
                      </td>
                      <td className="num">{b.rows}</td>
                      <td className="num">{b.accepted}</td>
                      <td className="num">{b.quarantined}</td>
                      <td className="num">{b.rejected}</td>
                      <td>
                        <button type="button" className="btn btn-sm" onClick={() => setSelected(b)} aria-label={`Open batch ${b.seq} ${b.file_name}`}>
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </Section>
    </>
  );
}

function toIsoWat(local: string): string {
  // datetime-local has no zone; NGSIRS extracts are stamped in WAT (UTC+01:00).
  return local.length === 16 ? `${local}:00+01:00` : `${local}+01:00`;
}

function UploadForm({ onCreated }: { onCreated: (b: ImportBatchOut) => void }) {
  const templates = useAsync(() => unwrap<FeedTemplate[]>(api.GET("/api/v1/imports/templates")), []);
  const sources = useAsync(() => unwrap<DataSource[]>(api.GET("/api/v1/data-sources")), []);
  const ref = useReference();
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [feed, setFeed] = useState("");
  const [extracted, setExtracted] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [lga, setLga] = useState("");
  const [mapping, setMapping] = useState("");
  const [mappingError, setMappingError] = useState<string | null>(null);

  const m = useMutation(() =>
    unwrap<ImportBatchOut>(
      api.POST("/api/v1/imports", {
        params: { header: { "Idempotency-Key": idempotencyKey() } },
        body: {
          // The generated type declares the binary part as string; the serializer below sends the File.
          file: file as unknown as string,
          source,
          feed_type: feed,
          extracted_at: toIsoWat(extracted),
          coverage_from: from || null,
          coverage_to: to || null,
          coverage_lga: lga || null,
          field_mapping: mapping.trim() || null,
        },
        bodySerializer(body) {
          const fd = new FormData();
          for (const [k, v] of Object.entries(body)) {
            if (v === null || v === undefined) continue;
            fd.append(k, v as string | Blob);
          }
          return fd;
        },
      }),
    ),
  );

  const sourcesForFeed = (sources.data ?? []).filter((s) => !feed || s.feed_types.includes(feed));
  const tpl = templates.data?.find((t) => t.feed_type === feed);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (mapping.trim()) {
      try {
        const parsed: unknown = JSON.parse(mapping);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
        setMappingError(null);
      } catch {
        setMappingError('Field mapping must be a JSON object, e.g. {"EmployerID": "employer_id"}');
        return;
      }
    }
    const b = await m.run();
    if (b) onCreated(b);
  }

  return (
    <Section title="Upload extract" description="The file is validated and previewed; nothing reaches the canonical store until a data steward commits the batch.">
      <form className="stack-sm" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Feed type" htmlFor="u-feed" required>
            <select id="u-feed" value={feed} onChange={(e) => setFeed(e.target.value)} required>
              <option value="">Choose…</option>
              {templates.data?.map((t) => (
                <option key={t.feed_type} value={t.feed_type}>
                  {t.title} ({t.feed_type})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Source system" htmlFor="u-source" required>
            <select id="u-source" value={source} onChange={(e) => setSource(e.target.value)} required>
              <option value="">Choose…</option>
              {sourcesForFeed.map((s) => (
                <option key={s.id} value={s.source_name} disabled={!s.enabled}>
                  {s.source_name}
                  {s.enabled ? "" : " (disabled – no sharing basis)"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="File (CSV)" htmlFor="u-file" required hint="Maximum 50 MB">
            <input id="u-file" type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </Field>
          <Field label="Extracted at (WAT)" htmlFor="u-extracted" required hint="Sent with timezone +01:00">
            <input id="u-extracted" type="datetime-local" value={extracted} onChange={(e) => setExtracted(e.target.value)} required />
          </Field>
          <Field label="Coverage from" htmlFor="u-from" hint="YYYY-MM">
            <input id="u-from" type="text" pattern="\d{4}-\d{2}" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="Coverage to" htmlFor="u-to" hint="YYYY-MM">
            <input id="u-to" type="text" pattern="\d{4}-\d{2}" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <Field label="Coverage LGA" htmlFor="u-lga" hint="Leave blank for state-wide">
            <select id="u-lga" value={lga} onChange={(e) => setLga(e.target.value)}>
              <option value="">State-wide</option>
              {ref?.lgas.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Column mapping (optional JSON)" htmlFor="u-mapping" hint="Source column → canonical column, for extracts whose headers differ from the template.">
          <textarea id="u-mapping" className="code" style={{ minHeight: "5rem" }} value={mapping} onChange={(e) => setMapping(e.target.value)} placeholder='{"EmployerID": "employer_id"}' aria-invalid={!!mappingError} />
        </Field>
        {mappingError && <StateMessage state="error" title="Invalid column mapping">{mappingError}</StateMessage>}
        {tpl && (
          <p className="m0 small muted">
            Expected columns: {tpl.columns.map((c) => `${c.name}${c.required ? "*" : ""}`).join(", ")} (* required). Natural key: {tpl.natural_key.join(" + ")}.
          </p>
        )}
        <div>
          <button type="submit" className="btn btn-primary" disabled={m.pending || !file}>
            {m.pending ? "Validating…" : "Upload and validate"}
          </button>
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}

function BatchDetail({ batch, onChanged }: { batch: ImportBatchOut; onChanged: (b: ImportBatchOut) => void }) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [rowStatus, setRowStatus] = useState("");
  const commit = useMutation(() => unwrap<ImportBatchOut>(api.POST("/api/v1/imports/{batch_id}/commit", { params: { path: { batch_id: batch.id } } })));
  const rollback = useMutation(() =>
    unwrap<ImportBatchOut>(api.POST("/api/v1/imports/{batch_id}/rollback", { params: { path: { batch_id: batch.id } }, body: { reason } })),
  );
  const rows = useAsync(
    () =>
      unwrap<ImportRowsPage>(
        api.GET("/api/v1/imports/{batch_id}/rows", { params: { path: { batch_id: batch.id }, query: { status: rowStatus || undefined, page_size: 50 } } }),
      ),
    [batch.id, batch.qa_status, rowStatus],
  );
  const q = batch.quality as Record<string, unknown>;
  const headerErrors = (q.header_errors as string[] | undefined) ?? [];
  const unmapped = (q.unmapped_columns as string[] | undefined) ?? [];
  const fresh = (q.freshness as Record<string, unknown> | undefined) ?? {};

  return (
    <Section title={`Batch #${batch.seq}: ${batch.file_name}`} description={`${batch.source ?? "—"} · ${batch.feed_type} · ingested ${fmtDateTime(batch.ingested_at)} by ${String(batch.created_by ?? "—")}`}>
      <div aria-live="polite">
        {batch.qa_status === "rejected" ? (
          <StateMessage state="invalid_import" title="Invalid import — file rejected">
            {headerErrors.length > 0 ? <p className="m0">Header errors: {headerErrors.join("; ")}</p> : <p className="m0">The file failed validation and cannot be committed.</p>}
            {Object.keys((q.reasons as object) ?? {}).length > 0 && <p className="m0">Reasons: {Object.entries(q.reasons as Record<string, number>).map(([k, v]) => `${humanize(k)} (${v})`).join(", ")}</p>}
          </StateMessage>
        ) : batch.qa_status === "validated" ? (
          <StateMessage state="deferred" title="Validated — awaiting commit">Review the quality report, then commit or roll back.</StateMessage>
        ) : batch.qa_status === "committed" ? (
          <StateMessage state="approved" title="Committed">Committed by {String(batch.committed_by ?? "—")} {fmtDateTime(batch.committed_at as string | null)}.</StateMessage>
        ) : (
          <StateMessage state="closed" title={humanize(batch.qa_status)}>
            {batch.rolled_back_by ? `Rolled back by ${String(batch.rolled_back_by)}.` : null}
          </StateMessage>
        )}
        {batch.created === false && <StateMessage state="info" title="Duplicate upload">An identical file was already ingested; the existing batch is shown.</StateMessage>}
      </div>
      <KeyValues
        columns={3}
        items={[
          ["Rows", batch.rows],
          ["Accepted", batch.accepted],
          ["Quarantined", batch.quarantined],
          ["Rejected", batch.rejected],
          ["Duplicates", String(q.duplicate ?? 0)],
          ["Completeness", fmtPct(q.completeness as number | null, 0)],
          ["Freshness", fresh.stale ? `Stale — ${String(fresh.age_days_at_ingest ?? "?")} days old (SLA ${String(fresh.sla_days ?? "?")})` : "Within SLA"],
          ["Unmapped columns", unmapped.length ? unmapped.join(", ") : "None"],
          ["Content hash", <Hash key="h" value={batch.content_hash} />],
          ["Warnings", Object.entries((q.warnings as Record<string, number>) ?? {}).map(([k, v]) => `${humanize(k)} (${v})`).join(", ") || "None"],
          ["Quarantine reasons", Object.entries((q.reasons as Record<string, number>) ?? {}).map(([k, v]) => `${humanize(k)} (${v})`).join(", ") || "None"],
          ["Manifest signature", <Hash key="s" value={batch.manifest_signature as string | null} />],
        ]}
      />
      <div className="grid-2">
        {can("imports:commit") && batch.qa_status === "validated" && (
          <div className="stack-sm">
            <button
              type="button"
              className="btn btn-primary"
              disabled={commit.pending}
              onClick={async () => {
                const b = await commit.run();
                if (b) onChanged(b);
              }}
            >
              Commit batch
            </button>
            <ErrorNotice error={commit.error} />
          </div>
        )}
        {can("imports:rollback") && ["validated", "committed"].includes(batch.qa_status) && (
          <form
            className="row-end"
            onSubmit={async (e) => {
              e.preventDefault();
              const b = await rollback.run();
              if (b) onChanged(b);
            }}
          >
            <Field label="Rollback reason" htmlFor="rb-reason" required>
              <input id="rb-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
            </Field>
            <button type="submit" className="btn btn-danger" disabled={reason.trim().length < 3 || rollback.pending}>
              Roll back
            </button>
            <ErrorNotice error={rollback.error} />
          </form>
        )}
      </div>
      <div className="stack-sm">
        <Field label="Row results" htmlFor="rows-status">
          <select id="rows-status" value={rowStatus} onChange={(e) => setRowStatus(e.target.value)}>
            <option value="">All rows</option>
            <option value="accepted">Accepted</option>
            <option value="quarantined">Quarantined</option>
            <option value="rejected">Rejected</option>
          </select>
        </Field>
        <AsyncBlock state={rows} what="rows" empty={(d) => d.items.length === 0}>
          {(d) => (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption>
                  First {d.items.length} of {d.total} rows
                </caption>
                <thead>
                  <tr>
                    <th scope="col" className="num">Row</th>
                    <th scope="col">Natural ID</th>
                    <th scope="col">Status</th>
                    <th scope="col">Messages</th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((r) => (
                    <tr key={r.id}>
                      <td className="num">{r.row_number}</td>
                      <th scope="row">{r.natural_id ?? "—"}</th>
                      <td>
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="small">{r.messages.join("; ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </div>
    </Section>
  );
}

// --- quarantine -------------------------------------------------------------------------------

function Quarantine() {
  const { can } = useAuth();
  const [includeResolved, setIncludeResolved] = useState(false);
  const items = useAsync(
    () => unwrap<QuarantineItem[]>(api.GET("/api/v1/data-quality/quarantine", { params: { query: { include_resolved: includeResolved } } })),
    [includeResolved],
  );
  return (
    <Section title="Quarantine queue" description="Records that failed validation. They never reach rule evaluation until corrected at source; resolution is recorded, not silently fixed.">
      <label className="checkbox">
        <input type="checkbox" checked={includeResolved} onChange={(e) => setIncludeResolved(e.target.checked)} /> Include resolved records
      </label>
      <AsyncBlock state={items} what="quarantined records" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data" data-testid="quarantine-table">
              <caption>{d.length} quarantined records</caption>
              <thead>
                <tr>
                  <th scope="col">Record</th>
                  <th scope="col">Feed · batch · row</th>
                  <th scope="col">Employer</th>
                  <th scope="col">Reasons</th>
                  <th scope="col">Resolution</th>
                </tr>
              </thead>
              <tbody>
                {d.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">
                      {r.natural_id ?? "—"}
                      <details>
                        <summary className="small">Raw values</summary>
                        <JsonView value={r.raw} label={`Raw values for ${r.natural_id ?? r.id}`} />
                      </details>
                    </th>
                    <td>
                      {r.feed_type} · #{r.batch_seq ?? "—"} · row {r.row_number}
                    </td>
                    <td>{r.employer_ref ?? "—"}</td>
                    <td>
                      {r.reasons.map((x) => (
                        <StatusBadge key={x} tone="warning">
                          {humanize(x)}
                        </StatusBadge>
                      ))}
                      <div className="small">{r.messages.join("; ")}</div>
                    </td>
                    <td>
                      {r.resolution && r.resolution !== "escalated" ? (
                        <span>
                          {humanize(r.resolution)} by {r.resolved_by}
                        </span>
                      ) : can("quality:resolve") ? (
                        <ResolveForm item={r} onDone={() => void items.reload()} />
                      ) : (
                        <span className="muted">{r.resolution ? humanize(r.resolution) : "Unresolved"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncBlock>
    </Section>
  );
}

function ResolveForm({ item, onDone }: { item: QuarantineItem; onDone: () => void }) {
  const [resolution, setResolution] = useState<QuarantineResolutionCode | "">("");
  const [note, setNote] = useState("");
  const m = useMutation(() =>
    unwrap<unknown>(
      api.POST("/api/v1/data-quality/quarantine/{record_id}/resolve", {
        params: { path: { record_id: item.id } },
        body: { resolution: resolution as QuarantineResolutionCode, note },
      }),
    ),
  );
  const idp = `q-${item.id.slice(0, 8)}`;
  return (
    <form
      className="stack-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await m.run()) onDone();
      }}
    >
      {item.resolution === "escalated" && <StatusBadge tone="info">Escalated</StatusBadge>}
      <Field label="Resolution" htmlFor={`${idp}-res`}>
        <select id={`${idp}-res`} value={resolution} onChange={(e) => setResolution(e.target.value as QuarantineResolutionCode)} required>
          <option value="">Choose…</option>
          <option value="corrected_at_source">Corrected at source</option>
          <option value="excluded">Excluded</option>
          <option value="escalated">Escalate</option>
        </select>
      </Field>
      <Field label="Note" htmlFor={`${idp}-note`}>
        <input id={`${idp}-note`} type="text" value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
      </Field>
      <div>
        <button type="submit" className="btn btn-sm" disabled={!resolution || note.trim().length < 3 || m.pending}>
          Resolve
        </button>
      </div>
      <ErrorNotice error={m.error} />
    </form>
  );
}

// --- identity -----------------------------------------------------------------------------------

function IdentityQueue() {
  const { can } = useAuth();
  const [status, setStatus] = useState("pending_review");
  const items = useAsync(
    () => unwrap<IdentityMatchItem[]>(api.GET("/api/v1/identity-matches", { params: { query: { status: status || undefined } } })),
    [status],
  );
  return (
    <Section title="Identity match review" description="Probabilistic or conflicting links below the confidence gate. Until confirmed, findings for these employers stay on data hold.">
      <Field label="Status" htmlFor="im-status">
        <select id="im-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="pending_review">Pending review</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
          <option value="auto_linked">Auto-linked</option>
          <option value="retracted">Retracted</option>
          <option value="">All</option>
        </select>
      </Field>
      <AsyncBlock state={items} what="identity matches" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption>{d.length} matches</caption>
              <thead>
                <tr>
                  <th scope="col">Employer</th>
                  <th scope="col">Candidate taxpayer</th>
                  <th scope="col">Method</th>
                  <th scope="col" className="num">Confidence</th>
                  <th scope="col">Status</th>
                  <th scope="col">Decision</th>
                </tr>
              </thead>
              <tbody>
                {d.map((m) => (
                  <tr key={m.id}>
                    <th scope="row">
                      {m.employer_name ?? "—"}
                      <div className="small muted">
                        {m.employer_ref} · {m.employer_lga}
                      </div>
                    </th>
                    <td>
                      {m.candidate_name ?? "—"}
                      <div className="small muted">{m.candidate_taxpayer}</div>
                    </td>
                    <td className="small">
                      {humanize(m.match_type)}
                      {m.method?.rule ? ` · ${String(m.method.rule)}` : ""}
                      {m.method?.threshold !== undefined ? ` · gate ${String(m.method.threshold)}` : ""}
                    </td>
                    <td className="num">{fmtConfidence(m.confidence)}</td>
                    <td>
                      <StatusBadge status={m.status} />
                      {m.reviewer && <div className="small">by {m.reviewer}</div>}
                    </td>
                    <td>{can("identity:review") ? <IdentityDecisionForm match={m} onDone={() => void items.reload()} /> : <span className="muted">Data steward only</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncBlock>
    </Section>
  );
}

function IdentityDecisionForm({ match, onDone }: { match: IdentityMatchItem; onDone: () => void }) {
  const [decision, setDecision] = useState<IdentityDecisionCode | "">("");
  const [reason, setReason] = useState("");
  const m = useMutation(() =>
    unwrap<unknown>(
      api.POST("/api/v1/identity-matches/{match_id}/decision", {
        params: { path: { match_id: match.id } },
        body: { decision: decision as IdentityDecisionCode, reason },
      }),
    ),
  );
  const idp = `im-${match.id.slice(0, 8)}`;
  const options: IdentityDecisionCode[] = match.status === "pending_review" ? ["confirm", "reject"] : ["retract"];
  return (
    <form
      className="stack-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await m.run()) onDone();
      }}
    >
      <Field label="Decision" htmlFor={`${idp}-d`}>
        <select id={`${idp}-d`} value={decision} onChange={(e) => setDecision(e.target.value as IdentityDecisionCode)} required>
          <option value="">Choose…</option>
          {options.map((o) => (
            <option key={o} value={o}>
              {humanize(o)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Reason" htmlFor={`${idp}-r`}>
        <input id={`${idp}-r`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
      </Field>
      <div>
        <button type="submit" className="btn btn-sm" disabled={!decision || reason.trim().length < 3 || m.pending}>
          Record
        </button>
      </div>
      <ErrorNotice error={m.error} />
    </form>
  );
}

// --- sources & templates ------------------------------------------------------------------------

function Sources() {
  const sources = useAsync(() => unwrap<DataSource[]>(api.GET("/api/v1/data-sources")), []);
  return (
    <Section title="Data sources and freshness" description="Registered sources, their data-sharing basis and the age of the latest extract per feed.">
      <AsyncBlock state={sources} what="data sources" empty={(d) => d.length === 0}>
        {(d) => (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Data sources</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Owner · basis</th>
                  <th scope="col">Permitted purpose</th>
                  <th scope="col">Enabled</th>
                  <th scope="col">Feed freshness</th>
                </tr>
              </thead>
              <tbody>
                {d.map((s) => (
                  <tr key={s.id}>
                    <th scope="row">
                      {s.source_name}
                      <div className="small muted">
                        {s.system_of_record ? "System of record" : "Secondary"}
                        {s.is_external ? " · external" : ""}
                      </div>
                    </th>
                    <td>
                      {s.owner}
                      <div className="small muted">{s.data_sharing_basis || "No data-sharing basis recorded"}</div>
                    </td>
                    <td>{s.permitted_purpose}</td>
                    <td>{s.enabled ? <StatusBadge tone="success">Enabled</StatusBadge> : <StatusBadge tone="danger">Disabled</StatusBadge>}</td>
                    <td>
                      <ul className="m0 small">
                        {s.freshness.map((f, i) =>
                          f ? (
                            <li key={i}>
                              {f.feed_type}: {f.last_extracted_at ? `${fmtDateTime(f.last_extracted_at)} (${f.age_days} days)` : "never received"}{" "}
                              {f.stale ? <StatusBadge status="stale">Stale</StatusBadge> : <StatusBadge tone="success">Fresh</StatusBadge>} SLA {f.sla_days} days
                            </li>
                          ) : (
                            <li key={i}>{s.feed_types[i]}: no data</li>
                          ),
                        )}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AsyncBlock>
    </Section>
  );
}

function Templates() {
  const t = useAsync(() => unwrap<FeedTemplate[]>(api.GET("/api/v1/imports/templates")), []);
  return (
    <AsyncBlock state={t} what="feed templates" empty={(d) => d.length === 0}>
      {(d) => (
        <div className="stack">
          {d.map((f) => (
            <Section key={f.feed_type} title={`${f.title} (${f.feed_type})`} description={`${f.description} · Safeguard: ${f.safeguard} · Natural key: ${f.natural_key.join(" + ")}`} level={3}>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                <table className="data">
                  <caption className="ng-visually-hidden">Columns for {f.feed_type}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Column</th>
                      <th scope="col">Type</th>
                      <th scope="col">Required</th>
                      <th scope="col">Allowed values</th>
                      <th scope="col">Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {f.columns.map((c) => (
                      <tr key={c.name}>
                        <th scope="row">
                          <code>{c.name}</code>
                        </th>
                        <td>{c.type}</td>
                        <td>{c.required ? "Yes" : "No"}</td>
                        <td className="small">{c.values.join(", ") || "—"}</td>
                        <td className="small">{c.description || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          ))}
        </div>
      )}
    </AsyncBlock>
  );
}

// --- system connectors ---------------------------------------------------------------------------

const RUN_TONE: Record<string, "success" | "warning" | "danger" | "info"> = {
  succeeded: "success",
  no_new_data: "info",
  failed: "danger",
  validated: "warning",
  rejected: "danger",
  running: "info",
};

function Connectors() {
  const { can } = useAuth();
  const list = useAsync(() => unwrap<ConnectorItem[]>(api.GET("/api/v1/connectors")), []);
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <Section
        title="System connectors"
        description="Live links to source systems such as the NGSIRS revenue collection platform. Each connector pulls new records on a schedule (cursor-based, so nothing is fetched twice) and can also receive signed webhooks. Everything it brings in goes through the same validation, quarantine and audit as a file import."
      >
        <AsyncBlock state={list} what="connectors" empty={(d) => d.length === 0}>
          {(d) => (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption className="ng-visually-hidden">System connectors</caption>
                <thead>
                  <tr>
                    <th scope="col">Connector</th>
                    <th scope="col">Mode</th>
                    <th scope="col">Feeds</th>
                    <th scope="col">Credentials</th>
                    <th scope="col">Last run</th>
                    <th scope="col">Cursor</th>
                    <th scope="col"><span className="ng-visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {d.map((c) => (
                    <tr key={c.id}>
                      <th scope="row">
                        {c.name}
                        <div className="small muted mono">{c.code} · {c.source}</div>
                        {!c.enabled && <StatusBadge tone="danger">Disabled</StatusBadge>}
                      </th>
                      <td>
                        {humanize(c.mode)}
                        <div className="small muted">every {c.schedule_minutes} min</div>
                      </td>
                      <td className="small">{c.feeds.join(", ")}</td>
                      <td className="small">
                        API {c.secret_configured ? <StatusBadge tone="success">set</StatusBadge> : <StatusBadge tone="warning">missing</StatusBadge>}
                        {c.webhook_feed && (
                          <div>
                            Webhook {c.webhook_secret_configured ? <StatusBadge tone="success">set</StatusBadge> : <StatusBadge tone="warning">missing</StatusBadge>}
                          </div>
                        )}
                      </td>
                      <td>
                        {c.last_status ? <StatusBadge tone={RUN_TONE[c.last_status] ?? "info"}>{humanize(c.last_status)}</StatusBadge> : "Never run"}
                        <div className="small muted">{c.last_run_at ? fmtDateTime(c.last_run_at) : ""}</div>
                      </td>
                      <td className="small mono">{Object.values(c.state)[0]?.cursor ?? "—"}</td>
                      <td>
                        <button type="button" className="btn btn-sm" onClick={() => setSelected(c.code)}>
                          Details
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AsyncBlock>
      </Section>
      {selected && <ConnectorPanel code={selected} canRun={can("connectors:run")} onChanged={list.reload} />}
    </>
  );
}

function ConnectorPanel({ code, canRun, onChanged }: { code: string; canRun: boolean; onChanged: () => void }) {
  const detail = useAsync(
    () => unwrap<ConnectorDetail>(api.GET("/api/v1/connectors/{code}", { params: { path: { code } } })),
    [code],
  );
  const run = useMutation((feed: string) =>
    unwrap<ConnectorRunItem>(
      api.POST("/api/v1/connectors/{code}/run", { params: { path: { code }, query: { feed_type: feed } } }),
    ),
  );
  async function pull(feed: string) {
    const r = await run.run(feed);
    if (r) {
      detail.reload();
      onChanged();
    }
  }
  return (
    <Section title={`Connector ${code}`} description="Configuration, recent runs and a manual pull. Secrets are never shown; only whether they are configured.">
      <AsyncBlock state={detail} what="connector">
        {(c) => (
          <>
            <KeyValues
              items={[
                ["Base URL", <span className="mono" key="u">{c.base_url ?? "—"}</span>],
                ["Authentication", humanize(c.auth_type)],
                ["Webhook endpoint", c.webhook_feed ? <span className="mono" key="w">POST /api/v1/connectors/{c.code}/webhook</span> : "Not enabled"],
                ["Webhook feed", c.webhook_feed ?? "—"],
              ]}
            />
            {canRun && (
              <div className="row">
                {c.feeds.map((f) => (
                  <button key={f} type="button" className="btn btn-primary" disabled={run.pending || !c.enabled} onClick={() => pull(f)}>
                    {run.pending ? "Pulling…" : `Pull ${f} now`}
                  </button>
                ))}
              </div>
            )}
            <ErrorNotice error={run.error} />
            <div aria-live="polite">
              {run.result && (
                <p className="small">
                  Last pull: <StatusBadge tone={RUN_TONE[run.result.status] ?? "info"}>{humanize(run.result.status)}</StatusBadge>{" "}
                  {run.result.records_received} records received, {run.result.records_filtered} filtered out
                  {run.result.error ? ` · ${run.result.error}` : ""}
                </p>
              )}
            </div>
            <h3>Recent runs</h3>
            {c.runs.length === 0 ? (
              <StateMessage state="no_data">This connector has not run yet.</StateMessage>
            ) : (
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                <table className="data">
                  <caption className="ng-visually-hidden">Connector runs</caption>
                  <thead>
                    <tr>
                      <th scope="col">Started</th>
                      <th scope="col">Trigger</th>
                      <th scope="col">Status</th>
                      <th scope="col" className="num">Received</th>
                      <th scope="col" className="num">Filtered</th>
                      <th scope="col">Batch</th>
                      <th scope="col">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.runs.map((r) => (
                      <tr key={r.id}>
                        <td>{fmtDateTime(r.started_at)}</td>
                        <td>{humanize(r.trigger)}</td>
                        <td><StatusBadge tone={RUN_TONE[r.status] ?? "info"}>{humanize(r.status)}</StatusBadge></td>
                        <td className="num">{r.records_received}</td>
                        <td className="num">{r.records_filtered}</td>
                        <td><Hash value={r.batch_id} len={8} /></td>
                        <td className="small">{r.error ?? (r.cursor_to ? `up to ${r.cursor_to}` : "")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <JsonView value={c.config} label="Field mapping and paging configuration" />
          </>
        )}
      </AsyncBlock>
    </Section>
  );
}
