"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { ActionResult, TextField } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const DEMO_USERS: { user: string; role: string }[] = [
  { user: "analyst", role: "Risk analyst" },
  { user: "manager", role: "Compliance manager" },
  { user: "officer", role: "Compliance officer" },
  { user: "steward", role: "Data steward" },
  { user: "audit", role: "Audit manager" },
  { user: "legal", role: "Legal officer" },
  { user: "exec", role: "Executive" },
  { user: "security", role: "Security auditor" },
  { user: "admin", role: "State administrator" },
  { user: "steward2", role: "Data steward (four-eyes)" },
  { user: "analyst2", role: "Risk analyst (second)" },
  { user: "manager2", role: "Compliance manager (second)" },
  { user: "officer2", role: "Compliance officer (second)" },
  { user: "legal2", role: "Legal officer (second)" },
];
const DEMO_DOMAIN = "niger.taxcris.test";
const DEMO_PASSWORD = "Demo-Pass-2026!";

function LoginForm() {
  const { login, me, loading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const target = next && next.startsWith("/") && !next.startsWith("//") && next !== "/login" ? next : "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && me) router.replace(target);
  }, [loading, me, router, target]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace(target);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="main" className="login-wrap">
      <div className="card login-card">
        <div className="login-side">
          <div className="brand-mark" aria-hidden="true" style={{ background: "#fff", color: "var(--accent)" }}>
            TC
          </div>
          <h1>TaxCRIS</h1>
          <p>Integrated compliance risk management for State Internal Revenue Services.</p>
          <ul>
            <li>Risk signals are indicators for review — never proof of evasion.</li>
            <li>Every score is explainable and reproducible from its evidence.</li>
            <li>Consequential steps need a second person; every action is audited.</li>
          </ul>
          <p className="small" style={{ marginTop: "auto" }}>
            Authorised users only. Access to taxpayer records is logged.
          </p>
        </div>
        <form className="login-form" onSubmit={onSubmit} noValidate={false}>
          <h2>Sign in</h2>
          <TextField label="Email" type="email" value={email} onChange={setEmail} required autoComplete="username" />
          <TextField label="Password" type="password" value={password} onChange={setPassword} required autoComplete="current-password" />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
          <ActionResult error={error} success={null} />
          <div className="notice notice-info">
            <div className="notice-title">Demo accounts</div>
            <p className="small">
              Password for every demo user: <code>{DEMO_PASSWORD}</code>. Choose a role to fill the form:
            </p>
            <div className="demo-users">
              {DEMO_USERS.map((u) => (
                <button
                  key={u.user}
                  type="button"
                  onClick={() => {
                    setEmail(`${u.user}@${DEMO_DOMAIN}`);
                    setPassword(DEMO_PASSWORD);
                  }}
                >
                  {u.user} — {u.role}
                </button>
              ))}
            </div>
            <p className="tiny muted" style={{ marginTop: 6 }}>
              A second tenant (Kwara, nearly empty) uses <code>@kwara.taxcris.test</code>.
            </p>
          </div>
        </form>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
