"use client";

import { useMemo } from "react";
import { ActionResult, Badge, ConfidenceBadge, Hash, JsonBlock, SafeguardChip, useAction } from "@/components/ui";
import { apiPost } from "@/lib/api";
import { dateTime, humanize, money, num, pct } from "@/lib/format";
import { DIMENSIONS } from "@/lib/reference";
import type { AssessmentDetail, Safeguard, SignalOut } from "@/lib/types";

export type SignalCatalogue = Record<string, { dimension: string; title: string }>;

interface LegalRuleRef {
  rule_code?: string;
  rule_version?: number;
  deadline?: string;
}

function legalRuleOf(s: SignalOut): LegalRuleRef | null {
  const lr = (s.evidence_ref as Record<string, unknown>).legal_rule;
  return lr && typeof lr === "object" ? (lr as LegalRuleRef) : null;
}

/** Explainable score: dimension contributions, confidence, signals with safeguards and provenance, reproducibility. */
export function EvidencePanel({ a, catalogue, compact = false }: { a: AssessmentDetail; catalogue?: SignalCatalogue; compact?: boolean }) {
  const reproduce = useAction();
  const groups = useMemo(() => {
    const m = new Map<string, SignalOut[]>();
    for (const s of a.signals) m.set(s.reason_code, [...(m.get(s.reason_code) ?? []), s]);
    return [...m.entries()].sort((x, y) => Math.max(...y[1].map((s) => s.severity)) - Math.max(...x[1].map((s) => s.severity)));
  }, [a.signals]);
  const ruleVersions = useMemo(() => [...new Set(Object.values(a.obligation_versions).map(String))], [a.obligation_versions]);
  const totalWeight = Object.values(a.weights_applied).reduce((x, y) => x + y, 0);

  return (
    <div className="stack">
      {a.suppressed && (
        <div className="notice notice-warn" role="note">
          <div className="notice-title">Low confidence — refer for data verification</div>
          This assessment is suppressed from enforcement queues because its data confidence is below the approved threshold. Verify the underlying data before any taxpayer
          contact.
          {a.suppression_reason ? <div className="small">Reason: {a.suppression_reason}</div> : null}
        </div>
      )}

      <div className="grid-2">
        <div>
          <div className="field-label">Risk score (indicator for review)</div>
          <div className="score-ring">
            <span className="score-big">{num(a.score)}</span>
            <span className="muted">/ 100</span>
          </div>
          <div className="small muted">
            Exposure scenario: <strong>{money(a.exposure_estimate)}</strong> — an estimate from declared/historical figures, not collectible debt.
          </div>
        </div>
        <div>
          <div className="field-label">Data confidence</div>
          <div className="row" style={{ marginTop: 4 }}>
            <span className="score-big" style={{ fontSize: "1.6rem" }}>
              {pct(a.confidence, 0)}
            </span>
            <ConfidenceBadge value={a.confidence} />
          </div>
          <table className="data" style={{ marginTop: 6 }}>
            <caption className="sr-only">Confidence components</caption>
            <tbody>
              {Object.entries(a.confidence_components).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row" style={{ background: "transparent", position: "static" }}>
                    {humanize(k)}
                  </th>
                  <td className="num">{pct(v, 0)}</td>
                  <td style={{ width: "40%" }}>
                    <div className="mini-bar" aria-hidden="true">
                      <span style={{ width: `${v * 100}%`, background: v < 0.6 ? "#b7791f" : undefined }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3>Score composition</h3>
        <div className="table-wrap">
          <table className="data dim-table">
            <thead>
              <tr>
                <th scope="col">Dimension</th>
                <th scope="col" className="num">
                  Dimension score
                </th>
                <th scope="col" className="num">
                  Weight applied
                </th>
                <th scope="col" className="num">
                  Contribution (score × weight)
                </th>
                <th scope="col">
                  <span className="sr-only">Contribution bar</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {DIMENSIONS.map((dim) => {
                const s = a.dimension_scores[dim];
                const w = a.weights_applied[dim];
                const applicable = s !== null && s !== undefined;
                const contrib = applicable && w !== undefined ? s * w : null;
                return (
                  <tr key={dim}>
                    <td>{humanize(dim)}</td>
                    <td className="num">{applicable ? num(s) : <Badge tone="outline">Not applicable</Badge>}</td>
                    <td className="num">{w !== undefined ? pct(w, 1) : "—"}</td>
                    <td className="num">
                      <strong>{contrib !== null ? num(contrib, 2) : "—"}</strong>
                    </td>
                    <td className="bar-cell">
                      <div className="mini-bar" aria-hidden="true">
                        <span style={{ width: `${contrib !== null ? Math.min(100, contrib) : 0}%` }} />
                      </div>
                    </td>
                  </tr>
                );
              })}
              <tr>
                <th scope="row">Total</th>
                <td />
                <td className="num">{pct(totalWeight, 0)}</td>
                <td className="num">
                  <strong>{num(a.score, 2)}</strong>
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
        <p className="tiny muted">Weights are renormalised across applicable dimensions; a dimension with no applicable obligation is excluded rather than scored zero.</p>
      </div>

      <div>
        <h3>
          Signals ({a.signals.length}) <span className="small muted">— each is an indicator, with its evidence and safeguards</span>
        </h3>
        {a.signals.length === 0 && <p className="muted">No signals fired.</p>}
        {groups.map(([code, sigs], gi) => (
          <details key={code} open={!compact && gi < 2} className="signal" style={{ marginTop: 8 }}>
            <summary>
              <span className="row" style={{ display: "inline-flex" }}>
                <Badge tone="outline">{code}</Badge>
                {catalogue?.[code]?.title ?? humanize(sigs[0]?.dimension)}
                {sigs.some((s) => s.is_hypothesis) && <Badge tone="warn">Hypothesis</Badge>}
                <span className="small muted">
                  {sigs.length} signal{sigs.length === 1 ? "" : "s"} · max severity {num(Math.max(...sigs.map((s) => s.severity)), 0)}
                </span>
              </span>
            </summary>
            <div style={{ marginTop: 8 }}>
              {sigs.map((s) => (
                <SignalCard key={s.id} s={s} />
              ))}
            </div>
          </details>
        ))}
      </div>

      <div>
        <h3>Provenance &amp; reproducibility</h3>
        <dl className="kv">
          <dt>Model version</dt>
          <dd>v{a.model_version}</dd>
          <dt>Signal engine</dt>
          <dd>{a.ruleset_version}</dd>
          <dt>Legal rule versions</dt>
          <dd>
            {ruleVersions.length === 0 && <span className="small muted">None — no legal obligation was evaluated for these signals</span>}
            <div className="chips">
              {ruleVersions.map((v) => (
                <Badge key={v} tone="outline">
                  {v}
                </Badge>
              ))}
            </div>
            {ruleVersions.length > 0 && <details>
              <summary className="tiny">Per obligation period</summary>
              <ul className="tiny" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {Object.entries(a.obligation_versions).map(([p, v]) => (
                  <li key={p}>
                    {p}: {String(v)}
                  </li>
                ))}
              </ul>
            </details>}
          </dd>
          <dt>Evaluated</dt>
          <dd>{dateTime(a.evaluation_time)}</dd>
          <dt>Run</dt>
          <dd className="mono tiny">{a.run_id}</dd>
          <dt>Inputs hash</dt>
          <dd>
            <Hash value={a.inputs_hash} label="Inputs hash" />
          </dd>
          <dt>Output hash</dt>
          <dd>
            <Hash value={a.output_hash} label="Output hash" />
          </dd>
        </dl>
        <div className="row" style={{ marginTop: 10 }}>
          <button
            type="button"
            className="btn"
            disabled={reproduce.busy}
            onClick={() =>
              reproduce.run(
                () => apiPost("/v1/risk-assessments/{assessment_id}/reproduce", { path: { assessment_id: a.id } }),
                (r) =>
                  r.reproducible
                    ? `✓ Reproducible — recomputed score ${num(r.score, 2)}; inputs hash verified: ${r.inputs_hash_verified ? "yes" : "no"}; stored output ${r.stored_output_hash.slice(0, 16)}… = recomputed ${r.recomputed_output_hash.slice(0, 16)}…`
                    : `✕ NOT reproducible — stored output ${r.stored_output_hash.slice(0, 16)}… ≠ recomputed ${r.recomputed_output_hash.slice(0, 16)}… (inputs hash verified: ${r.inputs_hash_verified ? "yes" : "no"})`,
              )
            }
          >
            {reproduce.busy ? "Re-scoring…" : "Reproduce score"}
          </button>
          <span className="tiny muted">Re-runs the engine on the frozen input snapshot and compares hashes.</span>
        </div>
        <div style={{ marginTop: 8 }}>
          <ActionResult error={reproduce.error} success={reproduce.success} />
        </div>
      </div>
    </div>
  );
}

function SignalCard({ s }: { s: SignalOut }) {
  const lr = legalRuleOf(s);
  const safeguards = s.safeguards as unknown as Safeguard[];
  return (
    <div className={`signal ${s.is_hypothesis ? "signal-hyp" : ""}`}>
      <div className="signal-head">
        <div className="row">
          <strong>{s.rule_id}</strong>
          <Badge tone="outline">{humanize(s.dimension)}</Badge>
          {s.is_hypothesis && (
            <Badge tone="warn" title="This signal is a hypothesis to be tested, not an observed breach">
              Hypothesis — not an observed breach
            </Badge>
          )}
        </div>
        <div className="row small">
          <span>
            Severity <strong>{num(s.severity, 0)}</strong>
          </span>
          <span>
            Confidence <strong>{pct(s.confidence, 0)}</strong>
          </span>
          <span>
            Exposure <strong>{money(s.exposure)}</strong>
          </span>
        </div>
      </div>
      <p className="mb-0">{s.explanation}</p>
      {safeguards.length > 0 && (
        <div className="chips" style={{ marginTop: 6 }} aria-label="Safeguard checks">
          {safeguards.map((g, i) => (
            <SafeguardChip key={i} check={g.check} result={g.result} detail={g.detail} />
          ))}
        </div>
      )}
      <div className="row small" style={{ marginTop: 6 }}>
        <span>
          Recommended: <Badge tone="accent">{humanize(s.recommended_action)}</Badge>
        </span>
        {lr && (
          <span>
            Legal rule:{" "}
            <Badge tone="outline">
              {lr.rule_code} v{lr.rule_version}
            </Badge>
            {lr.deadline ? <span className="muted"> · deadline {lr.deadline}</span> : null}
          </span>
        )}
      </div>
      <JsonBlock value={s.evidence_ref} summary="Evidence reference" />
    </div>
  );
}
