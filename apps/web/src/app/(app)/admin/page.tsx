"use client";

import { useState, type FormEvent } from "react";
import { ActionResult, Badge, Card, ErrorBox, Loading, NoAccess, PageHead, SelectField, TextField, useAction, useAsync } from "@/components/ui";
import { apiGet, apiPost } from "@/lib/api";
import { ROLE_LABELS, roleLabel, useAuth } from "@/lib/auth";
import { ROLES } from "@/lib/reference";

export default function AdminPage() {
  const { me, can, canAny } = useAuth();
  const allowed = canAny("tenant.admin", "users.manage", "users.read");
  const users = useAsync(() => apiGet("/v1/users"), [], allowed && can("users.read"));
  const roles = useAsync(() => apiGet("/v1/roles"), [], allowed);

  if (!allowed || !me) return <NoAccess permission="users.read" />;
  const allPerms = [...new Set(Object.values(roles.data ?? {}).flat())].sort();

  return (
    <>
      <PageHead title="Administration" description="Tenant configuration, user accounts and the role–permission matrix. Role changes take effect at next sign-in." />
      <div className="stack">
        <div className="grid-2">
          <Card title="Tenant">
            <dl className="kv">
              <dt>Name</dt>
              <dd>{me.tenant.name}</dd>
              <dt>State code</dt>
              <dd>{me.tenant.state_code}</dd>
              <dt>Legal jurisdiction</dt>
              <dd>{me.tenant.legal_jurisdiction}</dd>
              <dt>Config version</dt>
              <dd>v{me.tenant.config_version}</dd>
              <dt>Tenant id</dt>
              <dd className="mono tiny">{me.tenant.id}</dd>
              <dt>Data</dt>
              <dd>
                <Badge tone="warn">Synthetic demo data</Badge>
              </dd>
            </dl>
          </Card>
          {can("users.manage") ? (
            <CreateUser onCreated={users.reload} />
          ) : (
            <Card title="User management">
              <p className="muted mb-0">Your role can view users but not create them.</p>
            </Card>
          )}
        </div>

        {can("users.read") && (
          <Card title={`Users${users.data ? ` (${users.data.length})` : ""}`} pad={false}>
            {users.error && <ErrorBox error={users.error} onRetry={users.reload} />}
            {users.loading && !users.data && <Loading />}
            {users.data && (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Email</th>
                      <th scope="col">Role</th>
                      <th scope="col">Active</th>
                      <th scope="col">MFA</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.data.map((u) => (
                      <tr key={u.id}>
                        <td>{u.full_name}</td>
                        <td className="mono small">{u.email}</td>
                        <td>{roleLabel(u.role)}</td>
                        <td>{u.is_active ? <Badge tone="ok">Active</Badge> : <Badge>Inactive</Badge>}</td>
                        <td>{u.mfa_enabled ? <Badge tone="ok">Enabled</Badge> : <Badge tone="warn">Not enrolled</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        <Card title="Role–permission matrix" pad={false}>
          {roles.error && <ErrorBox error={roles.error} onRetry={roles.reload} />}
          {roles.loading && !roles.data && <Loading />}
          {roles.data && (
            <div className="table-wrap">
              <table className="data">
                <caption className="sr-only">Permissions held by each role</caption>
                <thead>
                  <tr>
                    <th scope="col">Permission</th>
                    {Object.keys(roles.data).map((r) => (
                      <th key={r} scope="col" style={{ whiteSpace: "normal", minWidth: 80 }}>
                        {roleLabel(r)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {allPerms.map((p) => (
                    <tr key={p}>
                      <th scope="row" style={{ position: "static" }}>
                        <code>{p}</code>
                      </th>
                      {Object.entries(roles.data ?? {}).map(([r, perms]) => (
                        <td key={r} style={{ textAlign: "center" }}>
                          {perms.includes(p) ? (
                            <span aria-label="granted" style={{ color: "var(--accent)", fontWeight: 700 }}>
                              ✓
                            </span>
                          ) : (
                            <span className="sr-only">not granted</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function CreateUser({ onCreated }: { onCreated: () => void }) {
  const [f, setF] = useState({ email: "", full_name: "", role: "compliance_officer", password: "" });
  const act = useAction();

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (f.password.length < 12) return act.setError("Use a password of at least 12 characters.");
    const r = await act.run(() => apiPost("/v1/users", { body: { ...f, email: f.email.trim(), full_name: f.full_name.trim() } }), (u) => `User ${u.email} created as ${roleLabel(u.role)}.`);
    if (r) {
      setF({ email: "", full_name: "", role: "compliance_officer", password: "" });
      onCreated();
    }
  }

  return (
    <Card title="Create user">
      <form onSubmit={submit} className="stack-sm" aria-label="Create user">
        <div className="form-grid">
          <TextField label="Full name" value={f.full_name} onChange={(v) => setF({ ...f, full_name: v })} required />
          <TextField label="Email" type="email" value={f.email} onChange={(v) => setF({ ...f, email: v })} required autoComplete="off" />
          <SelectField label="Role" value={f.role} onChange={(v) => setF({ ...f, role: v })} options={ROLES.map((r) => ({ value: r, label: ROLE_LABELS[r] ?? r }))} />
          <TextField label="Initial password" type="password" value={f.password} onChange={(v) => setF({ ...f, password: v })} required autoComplete="new-password" hint="At least 12 characters; share out of band." />
        </div>
        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={act.busy}>
            {act.busy ? "Creating…" : "Create user"}
          </button>
        </div>
        <ActionResult error={act.error} success={act.success} />
      </form>
    </Card>
  );
}
