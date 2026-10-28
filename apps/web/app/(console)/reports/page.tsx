"use client";

import type { ReportListItem, ReportResult } from "@ngsirs/contracts";
import { StateMessage } from "@ngsirs/design";
import { useState } from "react";
import { PurposeSelect } from "@/components/PurposeSelect";
import { AsyncBlock, ErrorNotice, Field, PageHeader, RequirePermission, Section } from "@/components/ui";
import { api, saveText, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync, useMutation } from "@/lib/hooks";
import { fmtDateTime, humanize } from "@/lib/format";

export default function ReportsPage() {
  return (
    <RequirePermission permission="reports:read" what="Management Reports">
      <Reports />
    </RequirePermission>
  );
}

function Reports() {
  const { can } = useAuth();
  const list = useAsync(() => unwrap<ReportListItem[]>(api.GET("/api/v1/reports")), []);
  const [name, setName] = useState("");
  const [period, setPeriod] = useState("");
  const [purpose, setPurpose] = useState("");
  const active = name || list.data?.[0]?.name || "";
  const preview = useAsync(
    () => unwrap<ReportResult>(api.GET("/api/v1/reports/{name}", { params: { path: { name: active }, query: { format: "json", period: period || undefined } } })),
    [active, period],
    !!active,
  );
  const exportCsv = useMutation(async () => {
    const text = await unwrap<string>(
      api.GET("/api/v1/reports/{name}", {
        params: { path: { name: active }, query: { format: "csv", period: period || undefined }, header: { "X-Purpose": purpose } },
        parseAs: "text",
      }),
    );
    saveText(text, `${active}${period ? `_${period}` : ""}.csv`);
    return true;
  });

  return (
    <>
      <PageHeader
        eyebrow="Reporting"
        title="Management Reports"
        description="Exportable summaries carrying their method note and denominators. CSV exports require a declared purpose and are written to the audit log."
      />
      <AsyncBlock state={list} what="reports" empty={(d) => d.length === 0}>
        {(reports) => (
          <form className="filters panel" onSubmit={(e) => e.preventDefault()} aria-label="Report selection">
            <Field label="Report" htmlFor="rp-name">
              <select id="rp-name" value={active} onChange={(e) => setName(e.target.value)}>
                {reports.map((r) => (
                  <option key={r.name} value={r.name}>
                    {humanize(r.name)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Period" htmlFor="rp-period" hint="YYYY-MM; blank = all">
              <input id="rp-period" type="text" pattern="\d{4}-\d{2}" value={period} onChange={(e) => setPeriod(e.target.value)} size={8} />
            </Field>
            <p className="m0 small muted" style={{ maxWidth: "32rem" }}>
              {reports.find((r) => r.name === active)?.description}
            </p>
          </form>
        )}
      </AsyncBlock>

      {can("reports:export") ? (
        <Section title="Export CSV">
          <form
            className="row-end"
            onSubmit={(e) => {
              e.preventDefault();
              void exportCsv.run();
            }}
          >
            <PurposeSelect id="rp-purpose" value={purpose} onChange={setPurpose} preferred="management_reporting" />
            <button type="submit" className="btn btn-primary" disabled={!purpose || !active || exportCsv.pending}>
              Download CSV
            </button>
          </form>
          <div aria-live="polite">{exportCsv.result && <p className="m0 small">CSV generated and saved; the export was recorded with purpose “{humanize(purpose)}”.</p>}</div>
          <ErrorNotice error={exportCsv.error} />
        </Section>
      ) : (
        <StateMessage state="forbidden" title="Preview only">Your role can preview reports but not export them.</StateMessage>
      )}

      <AsyncBlock state={preview} what="report rows">
        {(r) => (
          <Section title={`Preview: ${humanize(r.meta.report)}`} description={`${r.meta.rows} rows · generated ${fmtDateTime(r.meta.generated_at)} by ${r.meta.generated_by}${r.meta.period ? ` · period ${r.meta.period}` : ""}`}>
            <StateMessage state="info" title="Method note" live="off">
              {r.meta.method_note}
            </StateMessage>
            {r.rows.length === 0 ? (
              <StateMessage state="no_data" />
            ) : (
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
                <table className="data">
                  <caption className="ng-visually-hidden">Report rows</caption>
                  <thead>
                    <tr>
                      {Object.keys(r.rows[0]).map((k) => (
                        <th key={k} scope="col">
                          {humanize(k)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {r.rows.slice(0, 200).map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((v, j) => (
                          <td key={j}>{v === null || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {r.rows.length > 200 && <p className="m0 small muted">Showing first 200 of {r.rows.length} rows; export CSV for all.</p>}
          </Section>
        )}
      </AsyncBlock>
    </>
  );
}
