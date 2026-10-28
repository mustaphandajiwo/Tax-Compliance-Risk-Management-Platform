"use client";

import { StateMessage } from "@ngsirs/design";
import { useId, type ReactNode } from "react";
import type { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <div className="page-header__desc">{description}</div>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

export function Section({
  title,
  children,
  actions,
  description,
  level = 2,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  description?: ReactNode;
  level?: 2 | 3;
}) {
  const id = useId();
  const H = level === 2 ? "h2" : "h3";
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel__head">
        <H id={id}>{title}</H>
        {actions && <div className="panel__actions">{actions}</div>}
      </div>
      {description && <div className="panel__desc">{description}</div>}
      {children}
    </section>
  );
}

/** Shows the API's own message, error code and trace id; conflicts tell the user to reload. */
export function ErrorNotice({ error, onRetry }: { error: ApiError | null; onRetry?: () => void }) {
  if (!error) return null;
  const state = error.isConflict ? "conflict" : error.isForbidden ? "forbidden" : "error";
  const title = error.isConflict
    ? "Conflict: the record changed or is not in a state that allows this"
    : error.isForbidden
      ? "Not permitted"
      : error.status === 404
        ? "Not found"
        : error.status === 422 || error.status === 400
          ? "The request was not accepted"
          : "Request failed";
  const details = detailText(error.details);
  return (
    <StateMessage state={state} title={title} live="assertive">
      <p className="m0">{error.message}</p>
      {details && <p className="m0 small">Details: {details}</p>}
      {error.isConflict && <p className="m0 small">The latest version has been reloaded. Review it before trying again.</p>}
      <p className="m0 small muted">
        Code <code>{error.code}</code>
        {error.traceId && (
          <>
            {" "}
            · Trace ID <code data-testid="trace-id">{error.traceId}</code>
          </>
        )}
      </p>
      {onRetry && (
        <button type="button" className="btn btn-quiet" onClick={onRetry}>
          Retry
        </button>
      )}
    </StateMessage>
  );
}

function detailText(details: unknown): string | null {
  if (details === null || details === undefined) return null;
  if (typeof details === "string") return details;
  if (Array.isArray(details)) {
    return details
      .map((d) => (d && typeof d === "object" && "msg" in d ? `${(d as { loc?: unknown[] }).loc?.join(".") ?? ""}: ${(d as { msg: string }).msg}` : JSON.stringify(d)))
      .join("; ");
  }
  if (typeof details === "object") {
    return Object.entries(details as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}`)
      .join("; ");
  }
  return String(details);
}

export function Loading({ what }: { what: string }) {
  return <StateMessage state="loading" title={`Loading ${what}`} />;
}

/** Render loading / error / empty states for a read, then children with the data. */
export function AsyncBlock<T>({
  state,
  what,
  empty,
  children,
}: {
  state: { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };
  what: string;
  empty?: (d: T) => boolean;
  children: (d: T) => ReactNode;
}) {
  if (state.error && !state.data) return <ErrorNotice error={state.error} onRetry={state.reload} />;
  if (!state.data) return <Loading what={what} />;
  if (empty?.(state.data)) return <StateMessage state="no_data">No {what} match the current filters.</StateMessage>;
  return <>{children(state.data)}</>;
}

export function KeyValues({ items, columns = 2 }: { items: [ReactNode, ReactNode][]; columns?: 1 | 2 | 3 }) {
  return (
    <dl className={`kv kv--${columns}`}>
      {items.map(([k, v], i) => (
        <div key={i} className="kv__item">
          <dt>{k}</dt>
          <dd>{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
  required,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor: string;
  required?: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>
        {label}
        {required && (
          <span aria-hidden="true" className="req">
            {" "}
            *
          </span>
        )}
      </label>
      {children}
      {hint && (
        <p className="field__hint" id={`${htmlFor}-hint`}>
          {hint}
        </p>
      )}
    </div>
  );
}

export function Hash({ value, len = 16 }: { value: string | null | undefined; len?: number }) {
  if (!value) return <>—</>;
  return (
    <code className="hash" title={value}>
      {value.length > len ? `${value.slice(0, len)}…` : value}
    </code>
  );
}

export function JsonView({ value, label }: { value: unknown; label: string }) {
  return (
    <pre className="json" aria-label={label} tabIndex={0}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="pager" aria-label="Pagination">
      <button type="button" className="btn btn-quiet" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span aria-live="polite">
        Page {page} of {pages} · {total} total
      </span>
      <button type="button" className="btn btn-quiet" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

/** Blocks a whole screen when the role lacks the permission; the API would answer 403 anyway. */
export function RequirePermission({
  permission,
  what,
  children,
}: {
  permission: string | string[];
  what: string;
  children: ReactNode;
}) {
  const { can, me } = useAuth();
  const perms = Array.isArray(permission) ? permission : [permission];
  if (perms.some((p) => can(p))) return <>{children}</>;
  return (
    <div className="stack">
      <StateMessage state="forbidden" title={`Your role cannot open ${what}`}>
        <p className="m0">
          Signed in as {me?.display_name} ({me?.roles.join(", ")}). This screen needs the permission{" "}
          <code>{perms.join(" or ")}</code>. Access is deny-by-default and every request is checked by the API.
        </p>
      </StateMessage>
    </div>
  );
}

export function Yes({ value, yes = "Yes", no = "No" }: { value: boolean | null | undefined; yes?: string; no?: string }) {
  if (value === null || value === undefined) return <>Unknown</>;
  return <>{value ? yes : no}</>;
}
