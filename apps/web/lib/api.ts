import { createApiClient, type ErrorBody } from "@ngsirs/contracts";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const TOKEN_KEY = "ngsirs.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: the session simply will not persist */
  }
}

/** The typed client generated from packages/contracts/openapi.json. */
export const api = createApiClient({ baseUrl: API_URL, getToken });

/** An API failure carrying the standard {error:{code,message,details,trace_id}} contract. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly traceId: string | null;

  constructor(status: number, body: Partial<ErrorBody> | null, fallback: string) {
    super(body?.message || fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code || (status === 0 ? "network_error" : `http_${status}`);
    this.details = body?.details ?? null;
    this.traceId = body?.trace_id ?? null;
  }

  get isConflict() {
    return this.status === 409;
  }
  get isForbidden() {
    return this.status === 403;
  }
}

function errorBody(error: unknown): Partial<ErrorBody> | null {
  if (error && typeof error === "object" && "error" in error) {
    const e = (error as { error: unknown }).error;
    if (e && typeof e === "object") return e as Partial<ErrorBody>;
  }
  return null;
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

/**
 * Resolve an openapi-fetch call to its data or throw an ApiError.
 * `T` lets callers narrow open-object responses to the hand-written view types in @ngsirs/contracts.
 */
export async function unwrap<T>(call: Promise<FetchResult<unknown>>): Promise<T> {
  let result: FetchResult<unknown>;
  try {
    result = await call;
  } catch (e) {
    throw new ApiError(0, null, `The API at ${API_URL} could not be reached (${(e as Error).message}).`);
  }
  const { data, error, response } = result;
  if (!response.ok) {
    if (response.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(response.status, errorBody(error), `Request failed with HTTP ${response.status}`);
  }
  return data as T;
}

export function idempotencyKey(): string {
  return crypto.randomUUID();
}

/** Ask the browser to save text content (CSV exports). Nothing is sent anywhere else. */
export function saveText(content: string, fileName: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
