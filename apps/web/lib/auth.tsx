"use client";

import type { Me } from "@ngsirs/contracts";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, getToken, setToken, setUnauthorizedHandler, unwrap } from "./api";

type Status = "loading" | "signed_out" | "ready" | "error";

interface AuthState {
  status: Status;
  me: Me | null;
  error: ApiError | null;
  signIn: (username: string) => Promise<void>;
  signOut: () => void;
  can: (permission: string) => boolean;
  hasRole: (role: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const loadMe = useCallback(async () => {
    try {
      const m = await unwrap<Me>(api.GET("/api/v1/me"));
      setMe(m);
      setError(null);
      setStatus("ready");
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401) {
        setToken(null);
        setMe(null);
        setStatus("signed_out");
      } else {
        setError(err);
        setStatus("error");
      }
    }
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setMe(null);
    setStatus("signed_out");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(signOut);
    if (getToken()) void loadMe();
    else setStatus("signed_out");
    return () => setUnauthorizedHandler(null);
  }, [loadMe, signOut]);

  const signIn = useCallback(
    async (username: string) => {
      const tok = await unwrap<{ access_token: string }>(
        api.POST("/api/v1/auth/dev-token", { body: { username } }),
      );
      setToken(tok.access_token);
      setStatus("loading");
      await loadMe();
    },
    [loadMe],
  );

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      error,
      signIn,
      signOut,
      can: (p) => !!me?.permissions.includes(p),
      hasRole: (r) => !!me?.roles.includes(r),
    }),
    [status, me, error, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Signed-in user; only call inside the console layout, which guarantees a session. */
export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("useMe called without a session");
  return me;
}
