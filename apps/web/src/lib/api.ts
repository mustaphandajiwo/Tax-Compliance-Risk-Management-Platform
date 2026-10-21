/**
 * Typed fetch client for the TaxCRIS API.
 *
 * Request/response types are derived from the OpenAPI contract generated into
 * packages/contracts/src/api.d.ts (`npm run generate:api`). The server is the
 * security boundary: the UI hides what a role cannot do, but every call is
 * authorised (and denials audited) server-side.
 */
import type { components, paths } from "@contracts/api";

export type Schemas = components["schemas"];

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "taxcris.token";

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly body?: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

type Method = "get" | "post";
type PathsWith<M extends Method> = {
  [P in keyof paths]: paths[P] extends Record<M, infer O> ? (O extends undefined | never ? never : P) : never;
}[keyof paths];

type Op<P extends keyof paths, M extends Method> = paths[P][M & keyof paths[P]];

type JsonOf<R> = R extends { content: { "application/json": infer J } } ? J : never;
type SuccessOf<O> = O extends { responses: infer R }
  ? R extends { 200: infer S }
    ? JsonOf<S>
    : R extends { 201: infer S }
      ? JsonOf<S>
      : R extends { 202: infer S }
        ? JsonOf<S>
        : unknown
  : unknown;

type QueryOf<O> = O extends { parameters: { query?: infer Q } } ? (Q extends undefined ? never : NonNullable<Q>) : never;
type PathParamsOf<O> = O extends { parameters: { path: infer Pp } } ? (Pp extends undefined ? never : Pp) : never;
type BodyOf<O> = O extends { requestBody: { content: { "application/json": infer B } } }
  ? B
  : O extends { requestBody?: { content: { "application/json": infer B } } }
    ? B
    : never;

type Opts<O> = ([PathParamsOf<O>] extends [never] ? { path?: undefined } : { path: PathParamsOf<O> }) & {
  query?: [QueryOf<O>] extends [never] ? undefined : Partial<Record<keyof QueryOf<O>, string | number | boolean | null | undefined>>;
  body?: [BodyOf<O>] extends [never] ? undefined : BodyOf<O>;
};

let onUnauthorized: (() => void) | null = null;
/** Registered by the auth provider: clears the session and redirects to /login. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

function buildUrl(path: string, pathParams?: Record<string, string>, query?: Record<string, unknown>): string {
  let url = path.replace(/\{(\w+)\}/g, (_, k: string) => encodeURIComponent(pathParams?.[k] ?? ""));
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  return API_URL + url;
}

function detailOf(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          const item = e as { loc?: unknown[]; msg?: string };
          const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
          return loc ? `${loc}: ${item.msg ?? ""}` : (item.msg ?? JSON.stringify(e));
        })
        .join("; ");
    }
    return JSON.stringify(d);
  }
  return `Request failed (HTTP ${status})`;
}

async function request<T>(method: string, url: string, body?: unknown, auth = true): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = auth ? getToken() : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(url, { method: method.toUpperCase(), headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, `Cannot reach the TaxCRIS API at ${API_URL}. Check that the backend is running.`);
  }
  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && auth && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, detailOf(parsed, res.status), parsed);
  }
  return parsed as T;
}

export function apiGet<P extends PathsWith<"get">>(path: P, opts?: Opts<Op<P, "get">>): Promise<SuccessOf<Op<P, "get">>> {
  return request("get", buildUrl(path, opts?.path as Record<string, string> | undefined, opts?.query as Record<string, unknown>));
}

export function apiPost<P extends PathsWith<"post">>(path: P, opts?: Opts<Op<P, "post">>): Promise<SuccessOf<Op<P, "post">>> {
  return request(
    "post",
    buildUrl(path, opts?.path as Record<string, string> | undefined, opts?.query as Record<string, unknown>),
    opts?.body,
    path !== "/v1/auth/login",
  );
}

/** Downloads a CSV export with the bearer token and hands it to the browser as a file. */
export async function downloadCsv(path: "/v1/exports/management-brief.csv" | "/v1/exports/alerts.csv", query: Record<string, string | undefined>, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(buildUrl(path, undefined, query), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = undefined;
    }
    if (res.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, detailOf(body, res.status), body);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.status ? `${e.detail} (HTTP ${e.status})` : e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}
