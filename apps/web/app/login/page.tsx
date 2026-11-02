"use client";

import type { Branding, DevUser } from "@taxrisk/contracts";
import { StateMessage } from "@taxrisk/design";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { SyntheticBanner, Wordmark } from "@/components/AppShell";
import { ErrorNotice } from "@/components/ui";
import { api, ApiError, unwrap } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useAsync } from "@/lib/hooks";
import { humanize } from "@/lib/format";

function nextPath(): string {
  if (typeof window === "undefined") return "/dashboard";
  const n = new URLSearchParams(window.location.search).get("next");
  // Only same-origin absolute paths; never redirect off-site.
  return n && n.startsWith("/") && !n.startsWith("//") && n !== "/login" ? n : "/dashboard";
}

export default function LoginPage() {
  const { signIn, status } = useAuth();
  const router = useRouter();
  const users = useAsync(() => unwrap<DevUser[]>(api.GET("/api/v1/auth/dev-users")), []);
  const brand = useAsync(() => unwrap<Branding>(api.GET("/api/v1/auth/branding")), []);
  const [username, setUsername] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (status === "ready") router.replace(nextPath());
  }, [status, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username) return;
    setPending(true);
    setError(null);
    try {
      await signIn(username);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="shell">
      <SyntheticBanner environment="demo" synthetic />
      <header className="topbar">
        <Wordmark authority={brand.data?.authority_name} />
      </header>
      <main id="main" className="login">
        <h1>Sign in</h1>
        {brand.data?.fictional_authority && (
          <p className="muted">
            {brand.data.authority_name} is a fictional revenue authority used for demonstrations. Each real authority is
            configured through its own jurisdiction pack.
          </p>
        )}
        <StateMessage state="info" title="SYNTHETIC DEMO — development sign-in">
          <p className="m0">
            Choose a synthetic user to explore the console with that role&apos;s permissions. This shortcut exists only in
            demo and test environments; production uses the authority&apos;s identity provider (OIDC) with multi-factor authentication. No real taxpayer data is
            present.
          </p>
        </StateMessage>
        {users.error && <ErrorNotice error={users.error} onRetry={users.reload} />}
        {!users.data && !users.error && <StateMessage state="loading" title="Loading demo users" />}
        {users.data && (
          <form onSubmit={onSubmit} className="stack">
            <fieldset className="user-picker">
              <legend>Demo user</legend>
              {users.data.map((u) => (
                <label key={u.username} className="user-option">
                  <input
                    type="radio"
                    name="username"
                    value={u.username}
                    checked={username === u.username}
                    onChange={() => setUsername(u.username)}
                  />
                  <span>
                    <span className="user-option__name">{u.display_name}</span>
                    <span className="user-option__meta">
                      <code>{u.username}</code> · {u.roles.map(humanize).join(", ")}
                      {u.unit ? ` · ${u.unit}` : ""}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            {error && <ErrorNotice error={error} />}
            <div>
              <button type="submit" className="btn btn-primary" disabled={!username || pending}>
                {pending ? "Signing in…" : "Sign in"}
              </button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
}
