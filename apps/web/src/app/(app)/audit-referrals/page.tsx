"use client";

import { CaseTable } from "@/components/CaseTable";
import { Card, ErrorBox, Loading, NoAccess, PageHead, useAsync } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useUserDirectory } from "@/lib/users";

export default function AuditReferralsPage() {
  const { can } = useAuth();
  const allowed = can("cases.read") && can("audits.decide");
  const users = useUserDirectory(allowed && can("users.read"));
  const pending = useAsync(() => apiGet("/v1/cases", { query: { status: "audit_referral_pending", limit: 100 } }), [], allowed);
  const active = useAsync(() => apiGet("/v1/cases", { query: { status: "audit_in_progress", limit: 100 } }), [], allowed);

  if (!allowed) return <NoAccess permission="audits.decide" />;

  return (
    <>
      <PageHead
        title="Audit referrals"
        description="Referrals raised by compliance managers. An audit manager other than the referrer decides each one. Approve only where the materiality statement and evidence justify an audit."
      />
      <div className="stack">
        <Card title={`Awaiting decision${pending.data ? ` (${pending.data.total})` : ""}`} pad={false}>
          {pending.error && <ErrorBox error={pending.error} onRetry={pending.reload} />}
          {pending.loading && !pending.data && <Loading />}
          {pending.data && <CaseTable items={pending.data.items} users={users} />}
        </Card>
        <Card title={`Audits in progress${active.data ? ` (${active.data.total})` : ""}`} pad={false}>
          {active.error && <ErrorBox error={active.error} onRetry={active.reload} />}
          {active.loading && !active.data && <Loading />}
          {active.data && <CaseTable items={active.data.items} users={users} />}
        </Card>
      </div>
    </>
  );
}
