"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Card, ConfidenceBadge, Empty, ErrorBox, Loading, NoAccess, PageHead, Pagination, SelectField, StatusBadge, TextField, useAsync } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanize, num } from "@/lib/format";
import { Datalist, SECTORS, useLgaOptions } from "@/lib/reference";

const LIMIT = 25;

export default function TaxpayersPage() {
  const { can } = useAuth();
  const allowed = can("taxpayers.read");
  const lgas = useLgaOptions(allowed && can("metrics.read"));
  const [draft, setDraft] = useState({ q: "", lga: "", sector: "", taxpayer_type: "", registration_status: "" });
  const [filters, setFilters] = useState(draft);
  const [offset, setOffset] = useState(0);

  const res = useAsync(
    () => apiGet("/v1/taxpayers", { query: { ...filters, limit: LIMIT, offset } }),
    [JSON.stringify(filters), offset],
    allowed,
  );

  if (!allowed) return <NoAccess permission="taxpayers.read" />;

  function submit(e: FormEvent) {
    e.preventDefault();
    setOffset(0);
    setFilters(draft);
  }

  return (
    <>
      <PageHead title="Taxpayers" description="Search the resolved taxpayer register. Opening a taxpayer record is logged in the audit trail with your identity and role." />
      <div className="stack">
        <Card>
          <form className="filters" onSubmit={submit} role="search" aria-label="Search taxpayers">
            <TextField label="Name or identifier" type="search" value={draft.q} onChange={(v) => setDraft({ ...draft, q: v })} placeholder="e.g. Sabon Gari" />
            <TextField label="LGA" value={draft.lga} onChange={(v) => setDraft({ ...draft, lga: v })} list="tp-lgas" placeholder="Any" />
            <TextField label="Sector" value={draft.sector} onChange={(v) => setDraft({ ...draft, sector: v })} list="tp-sectors" placeholder="Any" />
            <SelectField label="Type" value={draft.taxpayer_type} onChange={(v) => setDraft({ ...draft, taxpayer_type: v })} options={["business", "individual"]} allowEmpty />
            <SelectField label="Registration" value={draft.registration_status} onChange={(v) => setDraft({ ...draft, registration_status: v })} options={["registered", "unregistered", "deregistered"]} allowEmpty />
            <div className="row">
              <button className="btn btn-primary" type="submit">
                Search
              </button>
            </div>
          </form>
          <Datalist id="tp-lgas" options={lgas} />
          <Datalist id="tp-sectors" options={SECTORS} />
        </Card>
        <Card pad={false}>
          {res.error && (
            <div className="card-body">
              <ErrorBox error={res.error} onRetry={res.reload} />
            </div>
          )}
          {res.loading && !res.data && <Loading />}
          {res.data && (
            <div aria-busy={res.loading} aria-live="polite">
              {res.data.items.length === 0 ? (
                <Empty>No taxpayers match these filters.</Empty>
              ) : (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Name</th>
                        <th scope="col">Type</th>
                        <th scope="col">Registration</th>
                        <th scope="col">Operating</th>
                        <th scope="col">LGA</th>
                        <th scope="col">Sector</th>
                        <th scope="col">Roles</th>
                        <th scope="col" className="num">
                          Latest score
                        </th>
                        <th scope="col">Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {res.data.items.map((t) => (
                        <tr key={t.id}>
                          <td>
                            <Link href={`/taxpayers/${t.id}`}>{t.name}</Link>
                          </td>
                          <td>{humanize(t.taxpayer_type)}</td>
                          <td>
                            <StatusBadge status={t.registration_status} />
                          </td>
                          <td>
                            <StatusBadge status={t.operating_status} />
                          </td>
                          <td>{t.lga ?? "—"}</td>
                          <td>{t.sector ?? "—"}</td>
                          <td className="small">{[t.is_employer && "Employer", t.self_employed && "Self-employed"].filter(Boolean).join(", ") || "—"}</td>
                          <td className="num">{num(t.latest_score ?? null)}</td>
                          <td>
                            <ConfidenceBadge value={t.latest_confidence ?? null} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Pagination total={res.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
