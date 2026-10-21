"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiGet, apiPost, getToken, setToken, setUnauthorizedHandler } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (...perms: string[]) => boolean;
  canAny: (...perms: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    setToken(null);
    setMe(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setMe(null);
      if (window.location.pathname !== "/login") {
        const next = window.location.pathname + window.location.search;
        router.replace(`/login?next=${encodeURIComponent(next)}`);
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    apiGet("/v1/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tok = await apiPost("/v1/auth/login", { body: { email, password } });
    setToken(tok.access_token);
    const profile = await apiGet("/v1/auth/me");
    setMe(profile);
  }, []);

  const value = useMemo<AuthState>(() => {
    const perms = new Set(me?.permissions ?? []);
    return {
      me,
      loading,
      login,
      logout,
      can: (...p) => p.every((x) => perms.has(x)),
      canAny: (...p) => p.some((x) => perms.has(x)),
    };
  }, [me, loading, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export const ROLE_LABELS: Record<string, string> = {
  state_admin: "State administrator",
  data_steward: "Data steward",
  risk_analyst: "Risk analyst",
  compliance_officer: "Compliance officer",
  compliance_manager: "Compliance manager",
  audit_manager: "Audit manager",
  legal_officer: "Legal officer",
  executive: "Executive",
  security_auditor: "Security auditor",
};

export function roleLabel(role: string | undefined | null): string {
  if (!role) return "";
  return ROLE_LABELS[role] ?? role.replace(/_/g, " ");
}
