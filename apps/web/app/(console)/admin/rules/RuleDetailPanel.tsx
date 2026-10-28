"use client";

import type { BacktestResult, RuleDetail, RuleDiff, RuleVersion, ValidationReport } from "@ngsirs/contracts";
import { StateMessage, StatusBadge } from "@ngsirs/design";
import { useEffect, useState } from "react";
import { ErrorNotice, Field, Hash, JsonView, KeyValues, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMutation } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

const DEFAULT_AS_OF = "2026-10-01T00:00:00+01:00";
const APPROVER_ROLES = ["legal_approver", "compliance_manager"] as const;

function bumpPatch(v: string): string {
  const [a, b, c] = v.split(".").map((x) => Number(x) || 0);
  return `${a}.${b}.${c + 1}`;
}

export function RuleDetailPanel({ rule, onChanged, onClose }: { rule: RuleDetail; onChanged: () => void; onClose: () => void }) {
  const { can } = useAuth();
  const active = rule.versions.find((v) => v.id === rule.active_version_id) ?? null;
  return (
    <Section
      title={`${rule.rule_code} — ${rule.title}`}
      description={`${humanize(rule.domain)} · catalogue status: ${humanize(rule.catalogue_status)} · active version: ${active?.version ?? "none"}`}
      actions={
        <button type="button" className="btn btn-quiet" onClick={onClose}>
          Close rule
        </button>
      }
    >
      {rule.versions.length === 0 && (
        <StateMessage state="no_data" title="No versions">
          This catalogue entry is {humanize(rule.catalogue_status)} and has no implemented version.
        </StateMessage>
      )}
      {rule.versions
        .slice()
        .reverse()
        .map((v) => (
          <VersionCard key={v.id} v={v} isActive={v.id === rule.active_version_id} onChanged={onChanged} />
        ))}
      {rule.versions.length >= 2 && <DiffView rule={rule} />}
      {can("rules:activate") && active && <Rollback code={rule.rule_code} onChanged={onChanged} />}
      {can("rules:draft") && <DraftEditor rule={rule} onChanged={onChanged} />}
    </Section>
  );
}

function VersionCard({ v, isActive, onChanged }: { v: RuleVersion; isActive: boolean; onChanged: () => void }) {
  const { can, me } = useAuth();
  const [note, setNote] = useState("");
  const myApproverRoles = APPROVER_ROLES.filter((r) => me?.roles.includes(r));
  const [asRole, setAsRole] = useState<string>(myApproverRoles[0] ?? "");
  const [reason, setReason] = useState("");
  const [asOf, setAsOf] = useState(DEFAULT_AS_OF);
  const [pFrom, setPFrom] = useState("2025-09");
  const [pTo, setPTo] = useState("2026-08");
  const path = { params: { path: { version_id: v.id } } };

  const backtest = useMutation(() =>
    unwrap<BacktestResult>(api.POST("/api/v1/rules/versions/{version_id}/backtest", { ...path, body: { as_of: asOf, period_from: pFrom, period_to: pTo } })),
  );
  const submit = useMutation(() => unwrap<RuleVersion>(api.POST("/api/v1/rules/versions/{version_id}/submit", path)));
  const approve = useMutation(() =>
    unwrap<RuleVersion>(
      api.POST("/api/v1/rules/versions/{version_id}/approve", { ...path, body: { note, as_role: asRole as (typeof APPROVER_ROLES)[number] } }),
    ),
  );
  const reject = useMutation(() => unwrap<RuleVersion>(api.POST("/api/v1/rules/versions/{version_id}/reject", { ...path, body: { reason } })));
  const activate = useMutation(() => unwrap<RuleVersion>(api.POST("/api/v1/rules/versions/{version_id}/activate", { ...path, body: { reason } })));

  async function act(run: () => Promise<unknown>) {
    if (await run()) onChanged();
  }

  const storedBacktest = v.backtest && "candidate" in v.backtest ? (v.backtest as BacktestResult) : null;
  const shownBacktest = backtest.result ?? storedBacktest;

  return (
    <article className="panel" aria-label={`Version ${v.version}`}>
      <div className="panel__head">
        <h3>
          Version {v.version} {isActive && <StatusBadge tone="success">Active</StatusBadge>}
        </h3>
        <StatusBadge status={v.status} />
      </div>
      <KeyValues
        columns={3}
        items={[
          ["Author", v.author],
          ["Change note", v.change_note],
          ["Legal reference", v.legal_ref ?? "—"],
          ["Created", fmtDateTime(v.created_at)],
          ["Activated", v.activated_at ? `${fmtDateTime(v.activated_at)} by ${v.activated_by}` : "—"],
          ["Content hash", <Hash key="h" value={v.content_hash} />],
          ["Validation", v.validation ? (v.validation.valid ? "Valid" : `Invalid: ${v.validation.errors.join("; ")}`) : "—"],
        ]}
      />
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
        <table className="data">
          <caption>Approvals (signed)</caption>
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Approver</th>
              <th scope="col">When</th>
              <th scope="col">Note</th>
              <th scope="col">Signature · key</th>
            </tr>
          </thead>
          <tbody>
            {v.approvals.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No approvals yet. Requires legal approver and compliance manager, by two different people, neither the author.
                </td>
              </tr>
            )}
            {v.approvals.map((a, i) => (
              <tr key={i}>
                <th scope="row">{humanize(a.role)}</th>
                <td>{a.actor}</td>
                <td className="nowrap">{fmtDateTime(a.at)}</td>
                <td>{a.note}</td>
                <td>
                  <Hash value={a.signature} len={20} /> · <code>{a.key_id}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>JSON definition</summary>
        <JsonView value={v.definition} label={`Definition of version ${v.version}`} />
      </details>

      {can("rules:backtest") && (
        <form
          className="row-end"
          onSubmit={(e) => {
            e.preventDefault();
            void backtest.run();
          }}
          aria-label={`Backtest version ${v.version}`}
        >
          <Field label="As of" htmlFor={`bt-asof-${v.id}`}>
            <input id={`bt-asof-${v.id}`} type="text" value={asOf} onChange={(e) => setAsOf(e.target.value)} size={26} required />
          </Field>
          <Field label="Periods from" htmlFor={`bt-from-${v.id}`}>
            <input id={`bt-from-${v.id}`} type="text" pattern="\d{4}-\d{2}" value={pFrom} onChange={(e) => setPFrom(e.target.value)} size={8} required />
          </Field>
          <Field label="to" htmlFor={`bt-to-${v.id}`}>
            <input id={`bt-to-${v.id}`} type="text" pattern="\d{4}-\d{2}" value={pTo} onChange={(e) => setPTo(e.target.value)} size={8} required />
          </Field>
          <button type="submit" className="btn" disabled={backtest.pending}>
            {backtest.pending ? "Running backtest…" : "Run backtest (shadow)"}
          </button>
        </form>
      )}
      <ErrorNotice error={backtest.error} />
      <div aria-live="polite">{shownBacktest && <BacktestView b={shownBacktest} />}</div>
      {!shownBacktest && v.backtest && <p className="m0 small muted">Backtest note: {JSON.stringify(v.backtest)}</p>}

      <div className="row">
        {can("rules:draft") && v.status === "validated" && (
          <button type="button" className="btn btn-primary" disabled={submit.pending} onClick={() => void act(submit.run)}>
            Submit for approval
          </button>
        )}
      </div>
      <ErrorNotice error={submit.error} />

      {can("rules:approve") && ["pending_approval", "validated"].includes(v.status) && (
        <form
          className="stack-sm"
          onSubmit={async (e) => {
            e.preventDefault();
            const which = ((e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null)?.value;
            if (which === "reject") await act(reject.run);
            else await act(approve.run);
          }}
        >
          <div className="form-grid">
            <Field label="Approve as role" htmlFor={`ap-role-${v.id}`}>
              <select id={`ap-role-${v.id}`} value={asRole} onChange={(e) => setAsRole(e.target.value)}>
                {myApproverRoles.map((r) => (
                  <option key={r} value={r}>
                    {humanize(r)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Approval note" htmlFor={`ap-note-${v.id}`}>
              <input id={`ap-note-${v.id}`} type="text" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Field label="Rejection reason" htmlFor={`rj-reason-${v.id}`}>
              <input id={`rj-reason-${v.id}`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
          <div className="row">
            {v.status === "pending_approval" && (
              <button type="submit" value="approve" className="btn btn-primary" disabled={note.trim().length < 3 || !asRole || approve.pending}>
                Approve (signed)
              </button>
            )}
            <button type="submit" value="reject" className="btn btn-danger" disabled={reason.trim().length < 3 || reject.pending}>
              Reject
            </button>
          </div>
          <ErrorNotice error={approve.error ?? reject.error} />
        </form>
      )}

      {can("rules:activate") && ["approved", "retired"].includes(v.status) && (
        <form
          className="row-end"
          onSubmit={async (e) => {
            e.preventDefault();
            await act(activate.run);
          }}
        >
          <Field label="Activation reason" htmlFor={`act-${v.id}`}>
            <input id={`act-${v.id}`} type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
          </Field>
          <button type="submit" className="btn btn-primary" disabled={reason.trim().length < 3 || activate.pending}>
            Activate version {v.version}
          </button>
          <ErrorNotice error={activate.error} />
        </form>
      )}
    </article>
  );
}

function BacktestView({ b }: { b: BacktestResult }) {
  const sides = [
    { label: `Candidate ${b.rule}`, s: b.candidate },
    ...(b.active ? [{ label: `Active ${b.compared_with ?? ""}`, s: b.active }] : []),
  ];
  return (
    <StateMessage state="info" title={`Impact preview — ${b.rule}, as of ${fmtDateTime(b.as_of)}, periods ${b.periods[0]}–${b.periods[1]}`} live="off">
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
        <table className="data">
          <caption className="ng-visually-hidden">Backtest comparison</caption>
          <thead>
            <tr>
              <th scope="col">Rule set</th>
              <th scope="col" className="num">Evaluated (denominator)</th>
              <th scope="col" className="num">Findings</th>
              <th scope="col" className="num">Data holds</th>
              <th scope="col" className="num">Suppressed</th>
              <th scope="col">Bands</th>
              <th scope="col">By LGA</th>
            </tr>
          </thead>
          <tbody>
            {sides.map(({ label, s }) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td className="num">{s.evaluated}</td>
                <td className="num">{s.findings}</td>
                <td className="num">{s.data_holds}</td>
                <td className="num">{s.suppressed}</td>
                <td className="small">{Object.entries(s.bands).map(([k, n]) => `${humanize(k)} ${n}`).join(", ") || "—"}</td>
                <td className="small">{Object.entries(s.by_lga).map(([k, n]) => `${k} ${n}`).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="m0 small">
        Newly flagged: <strong>{b.newly_flagged_count}</strong> · No longer flagged: <strong>{b.no_longer_flagged_count}</strong>
        {b.compared_with ? ` (vs ${b.compared_with})` : " (no active version to compare)"} · shadow run by {b.generated_by}, writes no findings.
      </p>
      {b.newly_flagged.length > 0 && (
        <details>
          <summary>Newly flagged subjects ({b.newly_flagged_count})</summary>
          <ul className="m0 small">
            {b.newly_flagged.slice(0, 100).map((k) => (
              <li key={k}>
                <code>{k}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </StateMessage>
  );
}

function DiffView({ rule }: { rule: RuleDetail }) {
  const versions = rule.versions.map((v) => v.version);
  const [from, setFrom] = useState(versions[versions.length - 2]);
  const [to, setTo] = useState(versions[versions.length - 1]);
  const m = useMutation(() =>
    unwrap<RuleDiff>(api.GET("/api/v1/rules/{rule_code}/diff", { params: { path: { rule_code: rule.rule_code }, query: { from_version: from, to_version: to } } })),
  );
  return (
    <Section title="Version diff" level={3}>
      <form
        className="row-end"
        onSubmit={(e) => {
          e.preventDefault();
          void m.run();
        }}
      >
        <Field label="From" htmlFor="df-from">
          <select id="df-from" value={from} onChange={(e) => setFrom(e.target.value)}>
            {versions.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </Field>
        <Field label="To" htmlFor="df-to">
          <select id="df-to" value={to} onChange={(e) => setTo(e.target.value)}>
            {versions.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </Field>
        <button type="submit" className="btn">
          Compare
        </button>
      </form>
      <ErrorNotice error={m.error} />
      <div aria-live="polite">
        {m.result &&
          (m.result.changes.length === 0 ? (
            <StateMessage state="no_data" title="No differences" />
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption>
                  {m.result.changes.length} changes {m.result.from} → {m.result.to}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Path</th>
                    <th scope="col">Change</th>
                    <th scope="col">From</th>
                    <th scope="col">To</th>
                  </tr>
                </thead>
                <tbody>
                  {m.result.changes.map((c) => (
                    <tr key={c.path}>
                      <th scope="row">
                        <code>{c.path}</code>
                      </th>
                      <td>{humanize(c.change)}</td>
                      <td>
                        <code>{c.from === undefined ? "—" : JSON.stringify(c.from)}</code>
                      </td>
                      <td>
                        <code>{c.to === undefined ? "—" : JSON.stringify(c.to)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
      </div>
    </Section>
  );
}

function Rollback({ code, onChanged }: { code: string; onChanged: () => void }) {
  const [reason, setReason] = useState("");
  const m = useMutation(() => unwrap<RuleVersion>(api.POST("/api/v1/rules/{rule_code}/rollback", { params: { path: { rule_code: code } }, body: { reason } })));
  return (
    <Section title="Roll back" level={3} description="Re-activates the most recent retired version. Existing findings stay attributed to the version that produced them.">
      <form
        className="row-end"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await m.run()) onChanged();
        }}
      >
        <Field label="Rollback reason" htmlFor="rule-rb">
          <input id="rule-rb" type="text" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} required />
        </Field>
        <button type="submit" className="btn btn-danger" disabled={reason.trim().length < 3 || m.pending}>
          Roll back {code}
        </button>
      </form>
      <ErrorNotice error={m.error} />
    </Section>
  );
}

function DraftEditor({ rule, onChanged }: { rule: RuleDetail; onChanged: () => void }) {
  const latest = rule.versions[rule.versions.length - 1];
  const initial = latest
    ? { ...latest.definition, version: bumpPatch(String(latest.definition.version ?? latest.version)) }
    : { id: rule.rule_code, version: "1.0.0", title: rule.title, domain: rule.domain };
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const [note, setNote] = useState("");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  // Live validation against the server-side rule schema, debounced.
  useEffect(() => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(text);
      setParseError(null);
    } catch (e) {
      setParseError((e as Error).message);
      setReport(null);
      return;
    }
    const t = setTimeout(() => {
      unwrap<ValidationReport>(api.POST("/api/v1/rules/validate", { body: { definition: parsed } }))
        .then(setReport)
        .catch(() => setReport(null));
    }, 500);
    return () => clearTimeout(t);
  }, [text]);

  const m = useMutation(() => unwrap<RuleVersion>(api.POST("/api/v1/rules", { body: { definition: JSON.parse(text), change_note: note } })));

  return (
    <Section title="Draft new version" level={3} description="Edit the JSON definition. It is validated live; a valid draft becomes a 'validated' version that must be backtested and submitted.">
      <form
        className="stack-sm"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await m.run()) onChanged();
        }}
      >
        <Field label="Rule definition (JSON)" htmlFor="rd-json">
          <textarea id="rd-json" className="code" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} aria-describedby="rd-validation" />
        </Field>
        <div id="rd-validation" aria-live="polite">
          {parseError ? (
            <StateMessage state="error" title="Not valid JSON" live="off">
              {parseError}
            </StateMessage>
          ) : report ? (
            report.valid ? (
              <StateMessage state="approved" title="Definition valid" live="off" />
            ) : (
              <StateMessage state="insufficient_evidence" title={`${report.errors.length} validation errors`} live="off">
                <ul className="m0">
                  {report.errors.map((er) => (
                    <li key={er}>{er}</li>
                  ))}
                </ul>
              </StateMessage>
            )
          ) : (
            <p className="m0 small muted">Validating…</p>
          )}
        </div>
        <Field label="Change note" htmlFor="rd-note" required>
          <input id="rd-note" type="text" value={note} onChange={(e) => setNote(e.target.value)} minLength={3} required />
        </Field>
        <div>
          <button type="submit" className="btn btn-primary" disabled={!report?.valid || note.trim().length < 3 || m.pending}>
            Save draft version
          </button>
        </div>
        <ErrorNotice error={m.error} />
      </form>
    </Section>
  );
}
