"use client";

import type { TaxpayerSearchPage } from "@taxrisk/contracts";
import { StatusBadge } from "@taxrisk/design";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { AsyncBlock, Field, PageHeader, Pager, RequirePermission } from "@/components/ui";
import { api, unwrap } from "@/lib/api";
import { useAsync, useReference } from "@/lib/hooks";
import { fmtConfidence, humanize } from "@/lib/format";
import { useLabels } from "@/lib/auth";

const PAGE_SIZE = 50;

export default function TaxpayersPage() {
  return (
    <RequirePermission permission="taxpayers:read" what="Taxpayer Intelligence">
      <TaxpayerSearch />
    </RequirePermission>
  );
}

function TaxpayerSearch() {
  const labels = useLabels();
  const ref = useReference();
  const [q, setQ] = useState("");
  const [area, setArea] = useState("");
  const [applied, setApplied] = useState({ q: "", area: "" });
  const [page, setPage] = useState(1);
  const res = useAsync(
    () =>
      unwrap<TaxpayerSearchPage>(
        api.GET("/api/v1/taxpayers", {
          params: { query: { q: applied.q || undefined, area: applied.area || undefined, page, page_size: PAGE_SIZE } },
        }),
      ),
    [applied, page],
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setApplied({ q, area });
  }

  return (
    <>
      <PageHeader
        eyebrow="PAYE employers"
        title="Taxpayer Intelligence"
        description="Search employers and their linked taxpayer records. Identifiers are masked; a business address never establishes tax residency or jurisdiction."
      />
      <form className="filters panel" role="search" onSubmit={submit}>
        <Field label="Name, employer ref or taxpayer ref" htmlFor="t-q">
          <input id="t-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} size={32} />
        </Field>
        <Field label={labels.area} htmlFor="t-area">
          <select id="t-area" value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">All</option>
            {ref?.areas.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </Field>
        <button type="submit" className="btn btn-primary">
          Search
        </button>
      </form>
      <AsyncBlock state={res} what="taxpayers" empty={(d) => d.items.length === 0}>
        {(d) => (
          <>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Scrollable table">
              <table className="data">
                <caption>{d.total} employers</caption>
                <thead>
                  <tr>
                    <th scope="col">Employer</th>
                    <th scope="col">{labels.area}</th>
                    <th scope="col">Sector · segment</th>
                    <th scope="col">Linked taxpayer</th>
                    <th scope="col">Identity status</th>
                    <th scope="col">Duplicate-resolution warning</th>
                    <th scope="col">Tax-type eligibility</th>
                    <th scope="col">Obligation status</th>
                    <th scope="col" className="num">
                      Open findings
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((t) => (
                    <tr key={t.employer_ref}>
                      <th scope="row">
                        <Link href={`/taxpayers/${encodeURIComponent(t.employer_ref)}`}>{t.name}</Link>
                        <div className="small muted">
                          {t.employer_ref} · {humanize(t.status)}
                        </div>
                      </th>
                      <td>{t.area ?? "—"}</td>
                      <td>
                        {humanize(t.sector)} · {humanize(t.segment)}
                      </td>
                      <td>{t.taxpayer_ref ?? <span className="muted">Not linked</span>}</td>
                      <td>
                        <StatusBadge status={t.identity.status} />
                        <div className="small">Confidence {fmtConfidence(t.identity.confidence)}</div>
                      </td>
                      <td>
                        {t.duplicate_warning.length > 0 ? (
                          <StatusBadge tone="warning">Possible duplicate of {t.duplicate_warning.join(", ")}</StatusBadge>
                        ) : (
                          <span className="muted">None</span>
                        )}
                      </td>
                      <td>{t.tax_types.length ? t.tax_types.join(", ") : <span className="muted">None active</span>}</td>
                      <td>
                        {t.obligation_status === "no_obligation_record" ? (
                          <StatusBadge tone="warning">No obligation record</StatusBadge>
                        ) : (
                          t.obligation_status.split(",").map((s) => <StatusBadge key={s} status={s} />)
                        )}
                      </td>
                      <td className="num">{t.open_findings}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          </>
        )}
      </AsyncBlock>
    </>
  );
}
