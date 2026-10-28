"use client";

import type { Reference } from "@ngsirs/contracts";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, unwrap } from "./api";

export interface Async<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T | null) => void;
}

/**
 * Run an API read whenever `deps` change. Stale responses (from an earlier deps value) are dropped.
 * Pass `enabled = false` to skip (e.g. when the role lacks the permission).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(enabled);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await fnRef.current();
      if (mine === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, null, String(e)));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void run();
    else setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, run, ...deps]);

  return { data, error, loading, reload: run, setData };
}

export interface Mutation<A extends unknown[], T> {
  run: (...args: A) => Promise<T | undefined>;
  pending: boolean;
  error: ApiError | null;
  result: T | null;
  reset: () => void;
}

/** Wrap a write call: tracks pending state, keeps the last result or ApiError for display. */
export function useMutation<A extends unknown[], T>(fn: (...args: A) => Promise<T>): Mutation<A, T> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async (...args: A) => {
    setPending(true);
    setError(null);
    try {
      const r = await fnRef.current(...args);
      setResult(r);
      return r;
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, null, String(e)));
      setResult(null);
      return undefined;
    } finally {
      setPending(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setResult(null);
  }, []);

  return { run, pending, error, result, reset };
}

let referenceCache: Promise<Reference> | null = null;

/** Reference data (LGAs, purposes, treatments, users); fetched once per page load. */
export function useReference(): Reference | null {
  const [ref, setRef] = useState<Reference | null>(null);
  useEffect(() => {
    referenceCache ??= unwrap<Reference>(api.GET("/api/v1/reference")).catch((e) => {
      referenceCache = null;
      throw e;
    });
    referenceCache.then(setRef).catch(() => setRef(null));
  }, []);
  return ref;
}

/** After a 409 (stale expected_version or invalid transition), reload the record once. */
export function useReloadOnConflict(error: ApiError | null, reload: () => void) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    if (error?.isConflict) reloadRef.current();
  }, [error]);
}
