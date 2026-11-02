"use client";

import type { CycleMetric, CycleStage, CycleSummary } from "@taxrisk/contracts";
import { StateMessage } from "@taxrisk/design";
import Link from "next/link";
import { useState } from "react";
import { AsyncBlock, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useLabels } from "@/lib/auth";
import { useAsync } from "@/lib/hooks";
import { fmtDateTime, fmtInt, fmtPct } from "@/lib/format";

export default function CyclePage() {
  return (
    <RequirePermission permission="dashboard:read" what="the Compliance Cycle">
      <Cycle />
    </RequirePermission>
  );
}

function Cycle() {
  const labels = useLabels();
  const state = useAsync(() => unwrap<CycleSummary>(api.GET("/api/v1/cycle")), []);
  return (
    <>
      <PageHeader
        eyebrow={`All tax types · ${labels.authorityShort || labels.authority}`}
        title="Compliance Cycle"
        description="How the authority finds, prioritises, understands, treats and learns from compliance risk, measured from live data at each stage. Results from the last stage feed the next evaluation."
      />
      <AsyncBlock state={state} what="the compliance cycle">
        {(d) => <CycleBody d={d} />}
      </AsyncBlock>
    </>
  );
}

function metricValue(m: CycleMetric) {
  if (m.value === null || m.value === undefined) return "—";
  return m.unit === "rate" ? fmtPct(m.value) : fmtInt(m.value);
}

function CycleBody({ d }: { d: CycleSummary }) {
  const [selected, setSelected] = useState<CycleStage["key"]>("analyse");
  const stage = d.stages.find((s) => s.key === selected) ?? d.stages[0];
  const total = d.segments.reduce((n, s) => n + s.count, 0);
  return (
    <>
      <StateMessage state="info" title="Method" live="off">
        <p className="m0">{d.method_note}</p>
        <p className="m0 small muted">
          {d.as_of ? `Latest evaluation as at ${fmtDateTime(d.as_of)}` : "No evaluation yet"}
          {d.window ? ` · periods ${d.window[0]} to ${d.window[1]}` : ""} · generated {fmtDateTime(d.generated_at)}
        </p>
      </StateMessage>

      <div className="cycle-layout">
        <section className="panel cycle-ring-panel" aria-labelledby="cycle-ring-title">
          <h2 id="cycle-ring-title" className="ng-visually-hidden">
            Cycle stages
          </h2>
          <Ring stages={d.stages} selected={selected} onSelect={setSelected} />
          <ol className="cycle-steps" aria-label="Stages in order">
            {d.stages.map((s, i) => (
              <li key={s.key}>
                <button
                  type="button"
                  className={`cycle-step${s.key === selected ? " is-selected" : ""}`}
                  aria-pressed={s.key === selected}
                  onClick={() => setSelected(s.key)}
                  data-testid={`cycle-step-${s.key}`}
                >
                  <span className="cycle-step__n">{i + 1}</span>
                  <span className="cycle-step__label">{s.label}</span>
                  <span className="cycle-step__value">{fmtInt(s.headline.value)}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel" aria-labelledby="stage-title" aria-live="polite">
          <p className="eyebrow">
            Stage {d.stages.indexOf(stage) + 1} of {d.stages.length}
          </p>
          <h2 id="stage-title" className="m0">
            {stage.label}
          </h2>
          <p className="m0 muted">{stage.purpose}</p>
          <p className="m0">
            <span className="big-number">{fmtInt(stage.headline.value)}</span> {stage.headline.label}
          </p>
          <table className="data compact">
            <caption className="ng-visually-hidden">{stage.label} measures</caption>
            <tbody>
              {stage.metrics.map((m) => (
                <tr key={m.label}>
                  <th scope="row">{m.label}</th>
                  <td className="num">
                    {metricValue(m)}
                    {m.note && <div className="small muted">{m.note}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="m0 small muted">{stage.note}</p>
          <p className="m0">
            <Link href={stage.link} className="btn btn-quiet">
              Go to this stage
            </Link>
          </p>
        </section>
      </div>

      <Section
        title="Taxpayer behaviour"
        description="Every taxpayer and revenue account is placed in one segment by the pattern of its open signals across all tax types. The strategy column is the treatment approach for that segment."
      >
        <div className="segment-bar" role="img" aria-label="Share of taxpayers by behaviour segment">
          {d.segments
            .filter((s) => s.count > 0)
            .map((s) => (
              <span
                key={s.key}
                className={`segment-bar__part seg-${s.key}`}
                style={{ flexGrow: s.count }}
                title={`${s.label}: ${s.count}`}
              />
            ))}
        </div>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Behaviour segments">
          <table className="data" data-testid="segments-table">
            <caption>Behaviour segments, {fmtInt(total)} taxpayers and accounts</caption>
            <thead>
              <tr>
                <th scope="col">Segment</th>
                <th scope="col" className="num">
                  Count
                </th>
                <th scope="col" className="num">
                  Share
                </th>
                <th scope="col">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {d.segments.map((s) => (
                <tr key={s.key}>
                  <th scope="row">
                    <span className={`seg-dot seg-${s.key}`} aria-hidden="true" /> {s.label}
                  </th>
                  <td className="num">{fmtInt(s.count)}</td>
                  <td className="num">{s.share === null ? "—" : fmtPct(s.share)}</td>
                  <td>{s.strategy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        title="By tax type"
        description="On-time rates count only periods whose due date has passed with complete source coverage; the denominator is shown. A dash means nothing was due yet or the head has no return."
      >
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Compliance by tax type">
          <table className="data" data-testid="tax-type-table">
            <caption>Compliance and open risk by tax type</caption>
            <thead>
              <tr>
                <th scope="col">Tax type</th>
                <th scope="col" className="num">
                  Accounts
                </th>
                <th scope="col" className="num">
                  On-time filing
                </th>
                <th scope="col" className="num">
                  On-time payment
                </th>
                <th scope="col" className="num">
                  Open signals
                </th>
                <th scope="col" className="num">
                  Held (data)
                </th>
                <th scope="col" className="num">
                  Assess
                </th>
                <th scope="col" className="num">
                  Treat
                </th>
                <th scope="col" className="num">
                  Implement
                </th>
              </tr>
            </thead>
            <tbody>
              {d.by_tax_type.map((h) => (
                <tr key={h.tax_type}>
                  <th scope="row">
                    <Link href={`/risks?tax_type=${encodeURIComponent(h.tax_type)}`}>{h.name}</Link>
                    <div className="small muted">
                      <code>{h.tax_type}</code>
                    </div>
                  </th>
                  <td className="num">{fmtInt(h.accounts)}</td>
                  <td className="num">
                    {h.on_time_filing.value === null ? "—" : fmtPct(h.on_time_filing.value)}
                    <div className="small muted">of {fmtInt(h.on_time_filing.denominator)}</div>
                  </td>
                  <td className="num">
                    {h.on_time_payment.value === null ? "—" : fmtPct(h.on_time_payment.value)}
                    <div className="small muted">of {fmtInt(h.on_time_payment.denominator)}</div>
                  </td>
                  <td className="num">{fmtInt(h.open_findings)}</td>
                  <td className="num">{fmtInt(h.held)}</td>
                  <td className="num">{fmtInt(h.assess)}</td>
                  <td className="num">{fmtInt(h.treat)}</td>
                  <td className="num">{fmtInt(h.implement)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {d.precision.length > 0 && (
        <Section
          title="Rule precision"
          description="Closed signals per rule. Rules whose signals are often not substantiated are revised through the governed rule studio before the next cycle."
        >
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Rule precision">
            <table className="data">
              <caption>Outcomes of closed signals by rule</caption>
              <thead>
                <tr>
                  <th scope="col">Rule</th>
                  <th scope="col" className="num">
                    Confirmed
                  </th>
                  <th scope="col" className="num">
                    Not substantiated
                  </th>
                  <th scope="col" className="num">
                    Precision
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.precision.map((r) => (
                  <tr key={r.rule}>
                    <th scope="row">
                      <code>{r.rule}</code>
                    </th>
                    <td className="num">{fmtInt(r.confirmed)}</td>
                    <td className="num">{fmtInt(r.not_substantiated)}</td>
                    <td className="num">{r.precision === null ? "—" : fmtPct(r.precision)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </>
  );
}

/** Six arcs around a ring; the arrowheads show the direction of the cycle. */
function Ring({
  stages,
  selected,
  onSelect,
}: {
  stages: CycleStage[];
  selected: string;
  onSelect: (k: CycleStage["key"]) => void;
}) {
  const size = 340;
  const c = size / 2;
  const rOuter = 158;
  const rInner = 98;
  const gap = 0.05;
  const n = stages.length;
  const polar = (r: number, a: number) => [c + r * Math.sin(a), c - r * Math.cos(a)] as const;
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="cycle-ring" aria-hidden="true" focusable="false">
      {stages.map((s, i) => {
        const a0 = (i / n) * 2 * Math.PI + gap;
        const a1 = ((i + 1) / n) * 2 * Math.PI - gap;
        const am = (a0 + a1) / 2;
        const [x0, y0] = polar(rOuter, a0);
        const [x1, y1] = polar(rOuter, a1);
        const [x2, y2] = polar(rInner, a1);
        const [x3, y3] = polar(rInner, a0);
        // chevron in the gap after each arc, pointing clockwise to the next stage
        const ag = ((i + 1) / n) * 2 * Math.PI;
        const rm = (rOuter + rInner) / 2;
        const [tipx, tipy] = polar(rm, ag + 0.03);
        const [ox, oy] = polar(rm + 9, ag - 0.03);
        const [ix, iy] = polar(rm - 9, ag - 0.03);
        const [lx, ly] = polar((rOuter + rInner) / 2, am);
        const short = s.label.split(" ")[0];
        return (
          <g
            key={s.key}
            className={`cycle-arc${s.key === selected ? " is-selected" : ""}`}
            onClick={() => onSelect(s.key)}
          >
            <path
              d={`M ${x0} ${y0} A ${rOuter} ${rOuter} 0 0 1 ${x1} ${y1} L ${x2} ${y2} A ${rInner} ${rInner} 0 0 0 ${x3} ${y3} Z`}
            />
            <path className="cycle-arrow" d={`M ${ox} ${oy} L ${tipx} ${tipy} L ${ix} ${iy}`} />
            <text x={lx} y={ly - 6} textAnchor="middle" className="cycle-arc__label">
              {i + 1}. {short}
            </text>
            <text x={lx} y={ly + 12} textAnchor="middle" className="cycle-arc__value">
              {s.headline.value.toLocaleString()}
            </text>
          </g>
        );
      })}
      <text x={c} y={c - 8} textAnchor="middle" className="cycle-centre__title">
        Compliance
      </text>
      <text x={c} y={c + 12} textAnchor="middle" className="cycle-centre__title">
        cycle
      </text>
      <text x={c} y={c + 34} textAnchor="middle" className="cycle-centre__note">
        results feed the next run
      </text>
    </svg>
  );
}
