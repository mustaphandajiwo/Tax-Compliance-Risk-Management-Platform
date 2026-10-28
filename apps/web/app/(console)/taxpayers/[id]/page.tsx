"use client";

import type { IdentifierReveal, Taxpayer360 } from "@ngsirs/contracts";
import { RISK_LABEL, RiskIndicator, StateMessage, StatusBadge, type Tone } from "@ngsirs/design";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { PurposeSelect } from "@/components/PurposeSelect";
import { AsyncBlock, ErrorNotice, KeyValues, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtConfidence, fmtDate, fmtDateTime, fmtNGN, humanize } from "@/lib/format";

export default function Taxpayer360Page() {
  return (
    <RequirePermission permission="taxpayers:read" what="Taxpayer 360">
      <Taxpayer360View />
    </RequirePermission>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  accepted_on_time: "success",
  paid_on_time: "success",
  accepted_late: "warning",
  paid_late: "warning",
  missing: "danger",
  pending_processing: "info",
  possible_unallocated_receipt: "info",
  not_due: "neutral",
  unknown_no_coverage: "neutral",
};

function Taxpayer360View() {
  const { id } = useParams<{ id: string }>();
  const ref = decodeURIComponent(id);
  const t = useAsync(() => unwrap<Taxpayer360>(api.GET("/api/v1/taxpayers/{ref}", { params: { path: { ref } } })), [ref]);
  return <AsyncBlock state={t} what="the taxpayer record">{(d) => <View d={d} />}</AsyncBlock>;
}

function View({ d }: { d: Taxpayer360 }) {
  const { can } = useAuth();
  const periods = d.periods.slice(-12);
  return (
    <>
      <PageHeader
        eyebrow={
          <>
            <Link href="/taxpayers">Taxpayer Intelligence</Link> / Taxpayer 360
          </>
        }
        title={d.employer.name}
        description={`${d.employer.ref} · ${d.employer.lga ?? "—"} · ${humanize(d.employer.sector)} · ${humanize(d.employer.segment)}`}
        actions={<StatusBadge status={d.employer.status} />}
      />
      {d.duplicate_warning.length > 0 && (
        <StateMessage state="conflict" title="Possible duplicate taxpayer identities">
          Linked taxpayer may duplicate {d.duplicate_warning.join(", ")}. Resolve in the identity review queue before outward action.
        </StateMessage>
      )}
      {d.obligation_summary === "no_obligation_record" && (
        <StateMessage state="no_obligation">No PAYE obligation record exists for this employer. Findings cannot assert non-compliance.</StateMessage>
      )}

      <div className="grid-2">
        <Section title="Employer profile">
          <KeyValues
            items={[
              ["Employer ref", d.employer.ref],
              ["Tax office", d.employer.office ?? "—"],
              ["Activity", `${fmtDate(d.employer.activity_from)} – ${d.employer.activity_to ? fmtDate(d.employer.activity_to) : "present"}`],
              ["Source record", <code key="s">{d.employer.source_record}</code>],
            ]}
          />
        </Section>
        <Section title="Linked taxpayer">
          {d.taxpayer ? (
            <>
              <KeyValues
                items={[
                  ["Taxpayer", `${d.taxpayer.name} (${d.taxpayer.ref})`],
                  ["Type · status", `${humanize(d.taxpayer.type)} · ${humanize(d.taxpayer.status)}`],
                  ["Jurisdiction", d.taxpayer.jurisdiction ?? "—"],
                  [
                    "Identifiers (masked)",
                    d.taxpayer.identifiers.length ? (
                      <ul className="m0">
                        {d.taxpayer.identifiers.map((i) => (
                          <li key={i.type + i.masked}>
                            {i.type}: <code>{i.masked}</code> · {humanize(i.verification)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      "None recorded"
                    ),
                  ],
                ]}
              />
              {can("taxpayers:reveal_identifiers") && <Reveal employerRef={d.employer.ref} />}
            </>
          ) : (
            <StateMessage state="insufficient_evidence" title="No linked taxpayer">
              Identity is unresolved; findings for this employer stay on data hold.
            </StateMessage>
          )}
        </Section>
      </div>

      <div className="grid-2">
        <Section title="Identity match history">
          <p className="m0">
            Current: <StatusBadge status={d.identity.status} /> {d.identity.match_type && `· ${humanize(d.identity.match_type)}`} · confidence{" "}
            {fmtConfidence(d.identity.confidence)}
          </p>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Identity match history</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Status</th>
                  <th scope="col">Method</th>
                  <th scope="col" className="num">Confidence</th>
                  <th scope="col">Reviewer</th>
                </tr>
              </thead>
              <tbody>
                {d.identity.history.map((h, i) => (
                  <tr key={i}>
                    <td>{fmtDateTime(h.at)}</td>
                    <th scope="row">{humanize(h.status)}</th>
                    <td>{humanize(h.type)}</td>
                    <td className="num">{fmtConfidence(h.confidence)}</td>
                    <td>{h.reviewer ?? "System"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
        <Section title="Obligations">
          {d.obligations.length === 0 ? (
            <StateMessage state="no_obligation" />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption className="ng-visually-hidden">Tax obligations</caption>
                <thead>
                  <tr>
                    <th scope="col">Tax type</th>
                    <th scope="col">Obligation</th>
                    <th scope="col">Status</th>
                    <th scope="col">Effective</th>
                    <th scope="col">Exemption</th>
                  </tr>
                </thead>
                <tbody>
                  {d.obligations.map((o) => (
                    <tr key={o.source}>
                      <th scope="row">{o.tax_type}</th>
                      <td>{humanize(o.type)}</td>
                      <td>
                        <StatusBadge status={o.status} />
                      </td>
                      <td>
                        {fmtDate(o.effective_from)} – {o.effective_to ? fmtDate(o.effective_to) : "open"}
                      </td>
                      <td>{humanize(o.exemption)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <StateMessage state={d.reporting_risk.status === "unknown" ? "insufficient_evidence" : "info"} title={`Reporting risk: ${humanize(d.reporting_risk.status)}`} live="off">
            {d.reporting_risk.note}
          </StateMessage>
        </Section>
      </div>

      <Section title="Filing and payment status by period" description="Last 12 periods in the latest evaluation, with the legal version that set each due date. 'Unknown' means no source coverage — not compliant, not non-compliant.">
        {periods.length === 0 ? (
          <StateMessage state="no_data">No evaluated periods for this employer.</StateMessage>
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data period-grid">
              <caption className="ng-visually-hidden">Per-period filing and payment status</caption>
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Obligation</th>
                  <th scope="col">Return due</th>
                  <th scope="col">Filing</th>
                  <th scope="col">Payment</th>
                  <th scope="col" className="num">Declared payable</th>
                  <th scope="col" className="num">Paid (allocated)</th>
                  <th scope="col" className="num">Residual</th>
                  <th scope="col">Legal version</th>
                  <th scope="col">Holds</th>
                </tr>
              </thead>
              <tbody>
                {periods.map((p) => (
                  <tr key={p.period}>
                    <th scope="row">{p.period}</th>
                    <td>{humanize(p.obligation_status)}</td>
                    <td>{fmtDate(p.return_due_at)}</td>
                    <td>
                      <StatusBadge tone={STATUS_TONE[p.filing_status] ?? "neutral"}>{humanize(p.filing_status)}</StatusBadge>
                    </td>
                    <td>
                      <StatusBadge tone={STATUS_TONE[p.payment_status] ?? "neutral"}>{humanize(p.payment_status)}</StatusBadge>
                    </td>
                    <td className="num">{fmtNGN(p.declared_payable)}</td>
                    <td className="num">{fmtNGN(p.paid)}</td>
                    <td className="num">{fmtNGN(p.residual)}</td>
                    <td>
                      <code>{p.legal_version ?? "—"}</code>
                    </td>
                    <td>{p.holds.length ? p.holds.map(humanize).join(", ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="m0 small muted">Residual amounts are reconciliation differences, not assessed arrears.</p>
      </Section>

      <div className="grid-2">
        <Section title="Filings">
          <SimpleTable
            caption="Returns"
            head={["Reference", "Period", "Status", "Submitted", "Accepted", "Declared"]}
            rows={d.filings.map((f) => [f.ref, f.period, humanize(f.status), fmtDateTime(f.submitted_at), fmtDateTime(f.accepted_at), fmtNGN(f.amount_declared)])}
          />
        </Section>
        <Section title="Payments">
          <SimpleTable
            caption="Payments"
            head={["Reference", "Period", "Paid at", "Amount", "Settlement", "Allocation", "Reversal"]}
            rows={d.payments.map((p) => [p.ref, p.period ?? "—", fmtDateTime(p.paid_at), fmtNGN(p.amount), humanize(p.settlement_status), humanize(p.allocation_status), humanize(p.reversal_status)])}
          />
        </Section>
      </div>

      <Section title="Assessments" description="Only served assessments not under appeal or stay count as confirmed arrears.">
        <SimpleTable
          caption="Assessments"
          head={["Reference", "Period", "Amount", "Outstanding", "Status", "Appeal / stay", "Served"]}
          rows={d.assessments.map((a) => [a.ref, a.period ?? "—", fmtNGN(a.amount), fmtNGN(a.outstanding), humanize(a.status), humanize(a.appeal_status), fmtDate(a.served_on)])}
        />
      </Section>

      <Section title="Findings" description={RISK_LABEL}>
        {d.findings.length === 0 ? (
          <StateMessage state="no_data" title="No findings for this employer" />
        ) : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
            <table className="data">
              <caption className="ng-visually-hidden">Findings for this employer</caption>
              <thead>
                <tr>
                  <th scope="col">Finding</th>
                  <th scope="col">Rule</th>
                  <th scope="col">Period</th>
                  <th scope="col">Priority index</th>
                  <th scope="col">State</th>
                  <th scope="col">Case</th>
                </tr>
              </thead>
              <tbody>
                {d.findings.map((f) => (
                  <tr key={f.finding_id}>
                    <th scope="row">
                      {can("risks:read") ? <Link href={`/risks/${f.finding_id}`}>{f.finding_ref}</Link> : f.finding_ref}
                    </th>
                    <td>
                      <code>{f.rule.id}</code> {f.title}
                    </td>
                    <td>{f.tax_period}</td>
                    <td>
                      <RiskIndicator priority={f.priority_score} band={f.priority_band} note={f.priority_note} confidence={f.indicators.confidence} showLabel={false} />
                    </td>
                    <td>
                      <StatusBadge status={f.status} />
                    </td>
                    <td>{f.case ? <Link href={`/cases/${f.case.id}`}>{String(f.case.ref)}</Link> : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Cases">
        {d.cases.length === 0 ? (
          <StateMessage state="no_data" title="No cases" />
        ) : (
          <ul className="m0">
            {d.cases.map((c) => (
              <li key={c.id}>
                <Link href={`/cases/${c.id}`}>{c.ref}</Link> · {humanize(c.treatment)} · <StatusBadge status={c.stage} />
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

function SimpleTable({ caption, head, rows }: { caption: string; head: string[]; rows: string[][] }) {
  if (rows.length === 0) return <StateMessage state="no_data" title={`No ${caption.toLowerCase()} on record`} />;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
      <table className="data">
        <caption className="ng-visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {head.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) =>
                j === 0 ? (
                  <th key={j} scope="row">
                    {c}
                  </th>
                ) : (
                  <td key={j}>{c}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Reveal({ employerRef }: { employerRef: string }) {
  const [purpose, setPurpose] = useState("");
  const m = useMutation(() =>
    unwrap<IdentifierReveal>(
      api.POST("/api/v1/taxpayers/{ref}/identifiers/reveal", { params: { path: { ref: employerRef }, header: { "X-Purpose": purpose } } }),
    ),
  );
  return (
    <details>
      <summary>Reveal full identifiers (audited)</summary>
      <form
        className="stack-sm"
        onSubmit={(e) => {
          e.preventDefault();
          void m.run();
        }}
      >
        <PurposeSelect id="rev-purpose" value={purpose} onChange={setPurpose} preferred="data_quality" />
        <div>
          <button type="submit" className="btn" disabled={!purpose || m.pending}>
            Reveal
          </button>
        </div>
        <div aria-live="polite">
          {m.result && (
            <ul className="m0">
              {m.result.identifiers.map((i) => (
                <li key={i.type}>
                  {i.type}: <code>{i.value}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </details>
  );
}
