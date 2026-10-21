"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { EvidencePanel, type SignalCatalogue } from "@/components/EvidencePanel";
import {
  ActionResult,
  Badge,
  Card,
  ConfidenceBadge,
  Empty,
  ErrorBox,
  Loading,
  NoAccess,
  Notice,
  PageHead,
  Pagination,
  ReasonField,
  reasonOk,
  SelectField,
  StatusBadge,
  TextField,
  useAction,
  useAsync,
} from "@/components/ui";
import { ApiError, apiGet, apiPost, downloadCsv, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanize, money, num, PERIOD_RE } from "@/lib/format";
import { ALERT_STATUSES, Datalist, SECTORS, TAX_TYPES, useLgaOptions } from "@/lib/reference";
import type { AlertOut } from "@/lib/types";

const LIMIT = 20;

interface Filters {
  status: string;
  tax_type: string;
  period: string;
  lga: string;
  sector: string;
  reason_code: string;
  min_confidence: string;
}

const DEFAULTS: Filters = { status: "open", tax_type: "", period: "", lga: "", sector: "", reason_code: "", min_confidence: "" };

export default function WorkbenchPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Workbench />
    </Suspense>
  );
}

function Workbench() {
  const { can } = useAuth();
  const allowed = can("risk.read");
  const params = useSearchParams();
  const router = useRouter();
  const directAssessment = params.get("assessment");
  const lgas = useLgaOptions(allowed && can("metrics.read"));
  const [draft, setDraft] = useState<Filters>(DEFAULTS);
  const [filters, setFilters] = useState<Filters>(DEFAULTS);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AlertOut | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const exportAction = useAction();

  const alerts = useAsync(
    () =>
      apiGet("/v1/alerts", {
        query: { ...filters, min_confidence: filters.min_confidence ? Number(filters.min_confidence) : undefined, limit: LIMIT, offset },
      }),
    [JSON.stringify(filters), offset],
    allowed,
  );
  const catalogue = useAsync(async () => {
    const c = (await apiGet("/v1/signal-catalogue")) as { signals?: SignalCatalogue };
    return c.signals ?? {};
  }, [], allowed);
  const model = useAsync(async () => (await apiGet("/v1/risk-models")).find((m) => m.status === "approved") ?? null, [], allowed);
  const minConf = model.data?.thresholds.min_confidence ?? 0.6;

  if (!allowed) return <NoAccess permission="risk.read" />;

  function apply(e: FormEvent) {
    e.preventDefault();
    if (draft.period && !PERIOD_RE.test(draft.period)) return setFormError("Period must be YYYY or YYYY-MM");
    if (draft.min_confidence && !(Number(draft.min_confidence) >= 0 && Number(draft.min_confidence) <= 1)) return setFormError("Minimum confidence must be between 0 and 1");
    setFormError(null);
    setOffset(0);
    setFilters(draft);
  }

  const assessmentId = selected?.assessment_id ?? directAssessment;

  return (
    <>
      <PageHead
        title="Risk workbench"
        description="Alerts are indicators for human review, ranked by priority. Open an alert to see the evidence behind its score before deciding. Nothing here is a finding of evasion."
        actions={
          can("exports.records") ? (
            <button
              type="button"
              className="btn"
              disabled={exportAction.busy}
              onClick={() =>
                exportAction.run(
                  () => downloadCsv("/v1/exports/alerts.csv", { status: filters.status || undefined, period: filters.period || undefined, tax_type: filters.tax_type || undefined }, "alerts.csv"),
                  "Alert export downloaded (masked for your role).",
                )
              }
            >
              Export alerts (CSV)
            </button>
          ) : undefined
        }
      />
      <div className="stack">
        <ActionResult error={exportAction.error} success={exportAction.success} />
        <Card>
          <form className="filters" onSubmit={apply} aria-label="Alert filters">
            <SelectField label="Status" value={draft.status} onChange={(v) => setDraft({ ...draft, status: v })} options={ALERT_STATUSES.map((s) => ({ value: s, label: s === "data_verification" ? "Data verification (low confidence)" : humanize(s) }))} allowEmpty emptyLabel="All" />
            <SelectField label="Tax type" value={draft.tax_type} onChange={(v) => setDraft({ ...draft, tax_type: v })} options={[...TAX_TYPES]} allowEmpty emptyLabel="All" />
            <TextField label="Period" value={draft.period} onChange={(v) => setDraft({ ...draft, period: v })} placeholder="YYYY or YYYY-MM" />
            <TextField label="LGA" value={draft.lga} onChange={(v) => setDraft({ ...draft, lga: v })} list="wb-lgas" placeholder="Any" />
            <TextField label="Sector" value={draft.sector} onChange={(v) => setDraft({ ...draft, sector: v })} list="wb-sectors" placeholder="Any" />
            <SelectField
              label="Reason code"
              value={draft.reason_code}
              onChange={(v) => setDraft({ ...draft, reason_code: v })}
              options={Object.entries(catalogue.data ?? {}).map(([k, v]) => ({ value: k, label: `${k} — ${v.title}` }))}
              allowEmpty
            />
            <TextField label="Min confidence" type="number" value={draft.min_confidence} onChange={(v) => setDraft({ ...draft, min_confidence: v })} placeholder="0–1" inputMode="decimal" />
            <div className="row">
              <button type="submit" className="btn btn-primary">
                Apply
              </button>
            </div>
          </form>
          <Datalist id="wb-lgas" options={lgas} />
          <Datalist id="wb-sectors" options={SECTORS} />
          {formError && (
            <p className="err small" role="alert" style={{ color: "var(--danger)", marginTop: 8 }}>
              {formError}
            </p>
          )}
        </Card>

        <div className="split split-queue">
          <Card title={`Alert queue${alerts.data ? ` (${alerts.data.total})` : ""}`} pad={false}>
            {alerts.error && (
              <div className="card-body">
                <ErrorBox error={alerts.error} onRetry={alerts.reload} />
              </div>
            )}
            {alerts.loading && !alerts.data && <Loading />}
            {alerts.data && (
              <div aria-busy={alerts.loading}>
                {alerts.data.items.length === 0 ? (
                  <Empty>No alerts match these filters.</Empty>
                ) : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th scope="col">Taxpayer</th>
                          <th scope="col">Status</th>
                          <th scope="col" className="num">
                            Priority
                          </th>
                          <th scope="col">Confidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {alerts.data.items.map((al) => (
                          <tr key={al.id} className={selected?.id === al.id ? "selected" : undefined}>
                            <td>
                              <button
                                type="button"
                                className="row-button"
                                aria-current={selected?.id === al.id ? "true" : undefined}
                                onClick={() => {
                                  setSelected(al);
                                  if (directAssessment) router.replace("/workbench");
                                }}
                                aria-label={`Open evidence for ${al.taxpayer_name ?? "taxpayer"} ${al.tax_type} ${al.period}`}
                              >
                                {al.taxpayer_name ?? al.taxpayer_id.slice(0, 8)}
                              </button>
                              <div className="tiny muted">
                                <strong>
                                  {al.tax_type} {al.period}
                                </strong>{" "}
                                · {al.lga ?? "—"} · {al.sector ?? "—"}
                              </div>
                              <div className="chips" style={{ marginTop: 3 }}>
                                {(al.reason_codes ?? []).map((r) => (
                                  <Badge key={r} tone={r === "REP-001" ? "warn" : "outline"} title={catalogue.data?.[r]?.title}>
                                    {r}
                                    {r === "REP-001" ? " · hypothesis" : ""}
                                  </Badge>
                                ))}
                              </div>
                            </td>
                            <td>
                              <StatusBadge status={al.status} label={al.status === "data_verification" ? "Data verification" : undefined} />
                            </td>
                            <td className="num">{num(al.priority)}</td>
                            <td>
                              <ConfidenceBadge value={al.confidence ?? null} threshold={minConf} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <Pagination total={alerts.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </div>
            )}
          </Card>

          <div className="stack" aria-live="polite">
            {!assessmentId && (
              <Card title="Evidence">
                <Empty>Select an alert to review its evidence, safeguards and provenance.</Empty>
              </Card>
            )}
            {selected && (
              <AlertDecision
                key={selected.id}
                alert={selected}
                onChanged={(a) => {
                  setSelected(a);
                  alerts.reload();
                }}
              />
            )}
            {assessmentId && <AssessmentCard key={assessmentId} id={assessmentId} catalogue={catalogue.data} />}
          </div>
        </div>
      </div>
    </>
  );
}

function AssessmentCard({ id, catalogue }: { id: string; catalogue?: SignalCatalogue }) {
  const res = useAsync(() => apiGet("/v1/risk-assessments/{assessment_id}", { path: { assessment_id: id } }), [id]);
  return (
    <Card
      title={
        <div>
          <h2 className="mb-0">Evidence panel</h2>
          {res.data && (
            <div className="small muted">
              <Link href={`/taxpayers/${res.data.taxpayer_id}`}>{res.data.taxpayer_name}</Link> · {res.data.tax_type} {res.data.period} · {res.data.lga} · {res.data.sector}
            </div>
          )}
        </div>
      }
    >
      {res.error && <ErrorBox error={res.error} onRetry={res.reload} />}
      {res.loading && !res.data && <Loading label="Loading evidence…" />}
      {res.data && <EvidencePanel a={res.data} catalogue={catalogue} />}
    </Card>
  );
}

function AlertDecision({ alert, onChanged }: { alert: AlertOut; onChanged: (a: AlertOut) => void }) {
  const { can } = useAuth();
  const [decision, setDecision] = useState<"confirm" | "dismiss" | "escalate">(alert.status === "data_verification" ? "escalate" : "confirm");
  const [reason, setReason] = useState("");
  const [justification, setJustification] = useState("");
  const triage = useAction();
  const caseAction = useAction();
  const [caseRef, setCaseRef] = useState<{ id: string; reference: string } | null>(null);
  const [duplicate, setDuplicate] = useState<string | null>(null);

  const triageable = ["open", "data_verification", "escalated"].includes(alert.status);
  const caseable = ["confirmed", "escalated"].includes(alert.status);
  const lowConfidence = alert.status === "data_verification";

  async function submitTriage(e: FormEvent) {
    e.preventDefault();
    if (!reasonOk(reason)) return triage.setError("A reason of at least 5 characters is required.");
    const r = await triage.run(
      () => apiPost("/v1/alerts/{alert_id}/triage", { path: { alert_id: alert.id }, body: { decision, reason: reason.trim() } }),
      (a) => `Alert ${humanize(a.status).toLowerCase()}. Your reason was recorded in the audit trail.`,
    );
    if (r) {
      setReason("");
      onChanged(r);
    }
  }

  async function openCase(e: FormEvent) {
    e.preventDefault();
    setDuplicate(null);
    if (!reasonOk(justification)) return caseAction.setError("A justification of at least 5 characters is required.");
    try {
      caseAction.reset();
      const c = await apiPost("/v1/cases", { body: { alert_id: alert.id, justification: justification.trim() } });
      setCaseRef({ id: c.id, reference: c.reference });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setDuplicate(err.detail);
      else caseAction.setError(errorMessage(err));
    }
  }

  return (
    <Card
      title={
        <div>
          <h2 className="mb-0">Review decision</h2>
          <div className="small muted">
            {alert.taxpayer_name} · {alert.tax_type} {alert.period} · exposure scenario {money(alert.exposure_estimate)}
          </div>
        </div>
      }
      actions={<StatusBadge status={alert.status} />}
    >
      <div className="stack-sm">
        {alert.triage_reason && (
          <p className="small mb-0">
            <strong>Last triage reason:</strong> {alert.triage_reason} <span className="muted">({alert.triaged_at?.slice(0, 16).replace("T", " ")})</span>
          </p>
        )}
        {lowConfidence && (
          <Notice tone="warn" title="Low confidence — refer for data verification">
            This alert cannot be confirmed until the underlying data is verified. You may escalate it for data verification follow-up or dismiss it with a reason.
          </Notice>
        )}
        {triageable && can("alerts.triage") && (
          <form onSubmit={submitTriage} className="stack-sm" aria-label="Triage alert">
            <fieldset>
              <legend>Decision</legend>
              <div className="radio-row">
                {(["confirm", "dismiss", "escalate"] as const).map((d) => (
                  <label key={d}>
                    <input type="radio" name={`decision-${alert.id}`} value={d} checked={decision === d} disabled={d === "confirm" && lowConfidence} onChange={() => setDecision(d)} />
                    {d === "confirm" ? "Confirm for follow-up" : d === "dismiss" ? "Dismiss" : "Escalate"}
                  </label>
                ))}
              </div>
            </fieldset>
            <ReasonField value={reason} onChange={setReason} />
            <div className="row">
              <button type="submit" className="btn btn-primary" disabled={triage.busy || !reasonOk(reason)}>
                {triage.busy ? "Recording…" : "Record decision"}
              </button>
              <span className="tiny muted">Confirming means the evidence merits proportionate follow-up — it is not a finding of evasion.</span>
            </div>
          </form>
        )}
        <ActionResult error={triage.error} success={triage.success} />
        {!triageable && !caseable && <p className="small muted mb-0">This alert has been {humanize(alert.status).toLowerCase()}; no further triage is possible.</p>}

        {caseable && can("cases.create") && !caseRef && (
          <form onSubmit={openCase} className="stack-sm" aria-label="Open case" style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <h3 className="mb-0">Open a case</h3>
            <ReasonField value={justification} onChange={setJustification} label="Case justification (mandatory)" />
            <div className="row">
              <button type="submit" className="btn btn-primary" disabled={!reasonOk(justification)}>
                Open case
              </button>
            </div>
          </form>
        )}
        {duplicate && (
          <Notice tone="warn" title="A case already exists">
            {duplicate}. Continue in the existing case instead of opening a duplicate.{" "}
            <Link href="/cases">Go to cases</Link>
          </Notice>
        )}
        <ActionResult error={caseAction.error} success={null} />
        {caseRef && (
          <Notice tone="ok" title="Case opened" live>
            Case <Link href={`/cases/${caseRef.id}`}>{caseRef.reference}</Link> was opened. Next step: propose a proportionate intervention for manager approval.
          </Notice>
        )}
      </div>
    </Card>
  );
}
