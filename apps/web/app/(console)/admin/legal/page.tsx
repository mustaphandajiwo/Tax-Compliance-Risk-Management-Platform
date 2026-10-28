"use client";

import type { LegalInstrument, LegalObligations, LegalResolve, LegalVersion } from "@ngsirs/contracts";
import { StateMessage, StatusBadge } from "@ngsirs/design";
import { useState, type FormEvent } from "react";
import { AsyncBlock, ErrorNotice, Field, Hash, KeyValues, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtDate, fmtDateTime, humanize } from "@/lib/format";

export default function LegalPage() {
  return (
    <RequirePermission permission="legal:read" what="the Legal Rules Library">
      <LegalLibrary />
    </RequirePermission>
  );
}

function LegalLibrary() {
  const { can } = useAuth();
  const obligations = useAsync(() => unwrap<LegalObligations>(api.GET("/api/v1/legal/obligations")), []);
  const instruments = useAsync(() => unwrap<LegalInstrument[]>(api.GET("/api/v1/legal/instruments")), []);
  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Legal Rules Library"
        description="Effective-dated statutory obligation versions that set due dates and parameters for every rule. A rule cannot be activated without an approved legal version."
      />
      <p className="notice-strong" role="note">
        {obligations.data?.notice ??
          "All parameters are SYNTHETIC placeholders pending NGSIRS legal confirmation from authenticated texts. No rate or deadline is taken from internet sources."}
      </p>

      <AsyncBlock state={obligations} what="obligation versions">
        {(d) => (
          <Section title="Obligation versions" description={`Taxpayer obligations by status: ${Object.entries(d.taxpayer_obligations_by_status).map(([k, v]) => `${humanize(k)} ${v}`).join(", ")}`}>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption className="ng-visually-hidden">Legal obligation versions</caption>
                <thead>
                  <tr>
                    <th scope="col">Code · version</th>
                    <th scope="col">Authority · instrument</th>
                    <th scope="col">Provision</th>
                    <th scope="col">Jurisdiction</th>
                    <th scope="col">Effective</th>
                    <th scope="col">Parameters</th>
                    <th scope="col">Status</th>
                    <th scope="col">Legal reviewer</th>
                    {can("legal:approve") && <th scope="col">Approve</th>}
                  </tr>
                </thead>
                <tbody>
                  {d.versions.map((v) => (
                    <tr key={v.id}>
                      <th scope="row">
                        <code>{v.code}</code>
                        <div>
                          {v.version} {v.is_synthetic && <StatusBadge tone="warning">Synthetic</StatusBadge>}
                        </div>
                      </th>
                      <td>
                        {v.authority ?? "—"}
                        <div className="small muted">
                          {v.instrument} — {v.instrument_title}
                        </div>
                      </td>
                      <td className="small">{v.provision_ref}</td>
                      <td>{v.jurisdiction}</td>
                      <td className="nowrap">
                        {fmtDate(v.effective_from)} – {v.effective_to ? fmtDate(v.effective_to) : "open"}
                      </td>
                      <td>
                        <code className="small">{JSON.stringify(v.parameters)}</code>
                      </td>
                      <td>
                        <StatusBadge status={v.status} />
                      </td>
                      <td className="small">
                        {v.approved_by ? (
                          <>
                            {v.approved_by}
                            <div className="muted">{fmtDateTime(v.approved_at)}</div>
                            {v.approval_note && <div>“{v.approval_note}”</div>}
                          </>
                        ) : (
                          <span className="muted">Not approved · drafted by {v.drafted_by}</span>
                        )}
                        <div>
                          <Hash value={v.content_hash} len={12} />
                        </div>
                      </td>
                      {can("legal:approve") && <td>{v.status === "pending_approval" ? <ApproveVersion v={v} onDone={() => void obligations.reload()} /> : "—"}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}
      </AsyncBlock>

      <div className="grid-2">
        <Resolver codes={Object.keys(obligations.data?.codes ?? {})} />
        <Section title="Legal instruments">
          <AsyncBlock state={instruments} what="instruments" empty={(d) => d.length === 0}>
            {(d) => (
              <ul className="m0 stack-sm" style={{ paddingLeft: "1.1rem" }}>
                {d.map((i) => (
                  <li key={i.id}>
                    <strong>{i.title}</strong> <code>{i.code}</code> · {i.authority} · {i.jurisdiction} <StatusBadge status={i.status} />
                    {i.is_synthetic && <StatusBadge tone="warning">Synthetic</StatusBadge>}
                    <div className="small muted">{i.source_note}</div>
                  </li>
                ))}
              </ul>
            )}
          </AsyncBlock>
        </Section>
      </div>

      {can("legal:draft") && obligations.data && instruments.data && (
        <DraftVersion obligations={obligations.data} instruments={instruments.data} onDone={() => void obligations.reload()} />
      )}
    </>
  );
}

function ApproveVersion({ v, onDone }: { v: LegalVersion; onDone: () => void }) {
  const [note, setNote] = useState("");
  const m = useMutation(() => unwrap<LegalVersion>(api.POST("/api/v1/legal/versions/{version_id}/approve", { params: { path: { version_id: v.id } }, body: { note } })));
  return (
    <form
      className="stack-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        if (await m.run()) onDone();
      }}
    >
      <Field label="Approval note" htmlFor={`lap-${v.id}`}>
        <input id={`lap-${v.id}`} type="text" value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
      </Field>
      <button type="submit" className="btn btn-sm" disabled={note.trim().length < 3 || m.pending}>
        Approve
      </button>
      <ErrorNotice error={m.error} />
    </form>
  );
}

function Resolver({ codes }: { codes: string[] }) {
  const [code, setCode] = useState("PAYE_EMPLOYER_MONTHLY_RETURN");
  const [period, setPeriod] = useState("2026-08");
  const m = useMutation(() => unwrap<LegalResolve>(api.GET("/api/v1/legal/resolve", { params: { query: { code, period } } })));
  return (
    <Section title="Resolve applicable law for a period" description="Which approved version governs a tax period, and the due date it implies.">
      <form
        className="row-end"
        onSubmit={(e) => {
          e.preventDefault();
          void m.run();
        }}
      >
        <Field label="Obligation code" htmlFor="lr-code">
          <select id="lr-code" value={code} onChange={(e) => setCode(e.target.value)}>
            {codes.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Tax period" htmlFor="lr-period">
          <input id="lr-period" type="text" pattern="\d{4}-\d{2}" value={period} onChange={(e) => setPeriod(e.target.value)} required size={8} />
        </Field>
        <button type="submit" className="btn">
          Resolve
        </button>
      </form>
      <div aria-live="polite">
        {m.result &&
          (m.result.approved_version ? (
            <StateMessage state="approved" title={`Resolved: ${m.result.approved_version.code}@${m.result.approved_version.version}`}>
              <KeyValues
                items={[
                  ["Instrument", `${m.result.approved_version.instrument} — ${m.result.approved_version.instrument_title}`],
                  ["Due at", fmtDateTime(m.result.due_at)],
                  ["Parameters", JSON.stringify(m.result.approved_version.parameters)],
                ]}
              />
            </StateMessage>
          ) : (
            <StateMessage state="no_obligation" title="Obligation unverified for this period">
              No approved legal version covers {m.result.period}.
              {m.result.unapproved_candidate && ` A candidate (${m.result.unapproved_candidate.version}, ${m.result.unapproved_candidate.status}) awaits approval.`}
            </StateMessage>
          ))}
      </div>
      <ErrorNotice error={m.error} />
    </Section>
  );
}

function DraftVersion({ obligations, instruments, onDone }: { obligations: LegalObligations; instruments: LegalInstrument[]; onDone: () => void }) {
  const codes = Object.keys(obligations.codes);
  const [code, setCode] = useState(codes[0] ?? "");
  const [version, setVersion] = useState("");
  const [instrument, setInstrument] = useState(instruments[0]?.code ?? "");
  const [provision, setProvision] = useState("SYNTHETIC placeholder provision - replace with authenticated reference");
  const [jurisdiction, setJurisdiction] = useState("NG-NI");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const required = obligations.codes[code]?.required ?? [];
  const [params, setParams] = useState("");
  const [paramError, setParamError] = useState<string | null>(null);
  const m = useMutation((parameters: Record<string, unknown>) =>
    unwrap<LegalVersion>(
      api.POST("/api/v1/legal/versions", {
        body: { code, version, instrument_code: instrument, provision_ref: provision, jurisdiction, effective_from: from, effective_to: to || null, parameters, is_synthetic: true },
      }),
    ),
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(params || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
      setParamError(null);
    } catch {
      setParamError("Parameters must be a JSON object.");
      return;
    }
    if (await m.run(parsed)) onDone();
  }

  return (
    <Section title="Draft a legal version" description="Drafts are synthetic until NGSIRS legal officers confirm them. A different legal approver must approve (maker-checker).">
      <form className="stack-sm" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Obligation code" htmlFor="ld-code" required>
            <select id="ld-code" value={code} onChange={(e) => setCode(e.target.value)}>
              {codes.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="Version label" htmlFor="ld-version" required hint="e.g. 2027.1-SYN">
            <input id="ld-version" type="text" value={version} onChange={(e) => setVersion(e.target.value)} required />
          </Field>
          <Field label="Instrument" htmlFor="ld-inst" required>
            <select id="ld-inst" value={instrument} onChange={(e) => setInstrument(e.target.value)}>
              {instruments.map((i) => (
                <option key={i.code} value={i.code}>
                  {i.code} — {i.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Jurisdiction" htmlFor="ld-jur" required>
            <input id="ld-jur" type="text" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} required />
          </Field>
          <Field label="Effective from" htmlFor="ld-from" required>
            <input id="ld-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          </Field>
          <Field label="Effective to" htmlFor="ld-to">
            <input id="ld-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
        </div>
        <Field label="Provision reference" htmlFor="ld-prov" required>
          <input id="ld-prov" type="text" value={provision} onChange={(e) => setProvision(e.target.value)} required />
        </Field>
        <Field label="Parameters (JSON)" htmlFor="ld-params" required hint={`Required keys: ${required.join(", ") || "none"}`}>
          <textarea
            id="ld-params"
            className="code"
            style={{ minHeight: "5rem" }}
            value={params}
            placeholder={JSON.stringify(Object.fromEntries(required.map((k) => [k, 0])))}
            onChange={(e) => setParams(e.target.value)}
            aria-invalid={!!paramError}
          />
        </Field>
        {paramError && <StateMessage state="error" title="Invalid parameters">{paramError}</StateMessage>}
        <div>
          <button type="submit" className="btn btn-primary" disabled={m.pending}>
            Save draft
          </button>
        </div>
        <div aria-live="polite">{m.result && <StateMessage state="deferred" title={`Draft saved: ${m.result.code}@${m.result.version}`}>Status: {humanize(m.result.status)}</StateMessage>}</div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}
