"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { errorMessage } from "@/lib/api";
import { humanize } from "@/lib/format";

/* ------------------------------------------------------------------ data hooks */

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T) => void;
}

/** Runs `fn` whenever `deps` change; ignores stale responses. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError(null);
    fnRef
      .current()
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setError(errorMessage(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload, setData };
}

/** Wraps a mutation with busy/error/success state for forms. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const run = useCallback(async <T,>(fn: () => Promise<T>, ok?: string | ((r: T) => string)): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const r = await fn();
      if (ok) setSuccess(typeof ok === "function" ? ok(r) : ok);
      return r;
    } catch (e) {
      setError(errorMessage(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  const reset = useCallback(() => {
    setError(null);
    setSuccess(null);
  }, []);
  return { busy, error, success, run, reset, setError };
}

/* ------------------------------------------------------------------ feedback */

export function Notice({ tone = "info", title, children, live }: { tone?: "info" | "warn" | "danger" | "ok"; title?: ReactNode; children?: ReactNode; live?: boolean }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "danger" ? "alert" : live ? "status" : undefined}>
      {title && <div className="notice-title">{title}</div>}
      {children}
    </div>
  );
}

/** Polite live region announcing async results of a form. Always mounted so screen readers pick up changes. */
export function ActionResult({ error, success }: { error: string | null; success: string | null }) {
  return (
    <div aria-live="polite" aria-atomic="true">
      {error && (
        <div className="notice notice-danger" role="alert">
          <div className="notice-title">Not completed</div>
          {error}
        </div>
      )}
      {success && <div className="notice notice-ok">{success}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="empty" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="notice notice-danger" role="alert">
      <div className="notice-title">Could not load</div>
      <div className="row-between">
        <span>{error}</span>
        {onRetry && (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/* ------------------------------------------------------------------ badges */

type Tone = "ok" | "warn" | "danger" | "info" | "accent" | "neutral" | "outline";

const STATUS_TONES: Record<string, Tone> = {
  // alerts
  open: "info",
  confirmed: "accent",
  dismissed: "neutral",
  escalated: "warn",
  data_verification: "warn",
  // cases
  pending_approval: "warn",
  approved: "accent",
  in_progress: "info",
  audit_referral_pending: "warn",
  audit_in_progress: "danger",
  closed: "neutral",
  // obligations
  filed: "ok",
  filed_late: "warn",
  overdue: "danger",
  met: "ok",
  not_applicable: "neutral",
  // rules/models
  draft: "neutral",
  submitted: "warn",
  pending: "warn",
  retired: "outline",
  superseded: "outline",
  // imports
  completed: "ok",
  processing: "info",
  queued: "info",
  failed: "danger",
  reconciled: "ok",
  unreconciled: "danger",
  accepted: "ok",
  rejected: "danger",
  duplicate: "neutral",
  quarantined: "warn",
  reprocessed: "ok",
  // merges
  candidate: "info",
  proposed: "warn",
  merged: "ok",
  rolled_back: "outline",
  // audit
  success: "ok",
  denied: "danger",
  failure: "danger",
  error: "danger",
  // safeguards
  pass: "ok",
  fail: "danger",
  warn: "warn",
  none: "neutral",
  required: "info",
  exempt: "neutral",
  executed: "ok",
  validating: "info",
  returned: "warn",
  // misc
  registered: "ok",
  unregistered: "warn",
  deregistered: "neutral",
  active: "ok",
  dormant: "warn",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  const cls = tone === "neutral" ? "badge" : `badge badge-${tone}`;
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  if (!status) return <span className="muted">—</span>;
  return <Badge tone={STATUS_TONES[status] ?? "neutral"}>{label ?? humanize(status)}</Badge>;
}

export function SafeguardChip({ check, result, detail }: { check: string; result: string; detail?: string }) {
  const symbol = result === "pass" ? "✓" : result === "fail" ? "✕" : result === "warn" ? "!" : result === "required" ? "?" : "·";
  return (
    <Badge tone={STATUS_TONES[result] ?? "neutral"} title={detail}>
      <span aria-hidden="true">{symbol}</span>
      {humanize(check)}: {result}
      {detail ? <span className="sr-only"> — {detail}</span> : null}
    </Badge>
  );
}

/** Confidence indicator. Below `threshold` the assessment is treated as low confidence (refer for data verification). */
export function ConfidenceBadge({ value, threshold = 0.6 }: { value: number | null | undefined; threshold?: number }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const low = value < threshold;
  return (
    <Badge tone={low ? "warn" : value >= 0.85 ? "ok" : "info"} title={low ? "Low confidence — refer for data verification" : undefined}>
      {(value * 100).toFixed(0)}%{low ? " · low" : ""}
    </Badge>
  );
}

/* ------------------------------------------------------------------ forms */

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`field ${className ?? ""}`}>
      <label htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && (
        <span id={hintId} className="hint">
          {hint}
        </span>
      )}
      {error && (
        <span id={errId} className="err">
          {error}
        </span>
      )}
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  hint,
  allowEmpty,
  emptyLabel = "Any",
  required,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: (string | { value: string; label: string })[];
  hint?: ReactNode;
  allowEmpty?: boolean;
  emptyLabel?: string;
  required?: boolean;
  className?: string;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(p) => (
        <select {...p} value={value} onChange={(e) => onChange(e.target.value)} required={required}>
          {allowEmpty && <option value="">{emptyLabel}</option>}
          {options.map((o) => {
            const opt = typeof o === "string" ? { value: o, label: humanize(o) } : o;
            return (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            );
          })}
        </select>
      )}
    </Field>
  );
}

export function TextField({
  label,
  value,
  onChange,
  hint,
  error,
  type = "text",
  placeholder,
  required,
  list,
  className,
  autoComplete,
  minLength,
  pattern,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: ReactNode;
  error?: string | null;
  type?: "text" | "email" | "password" | "number" | "search" | "date";
  placeholder?: string;
  required?: boolean;
  list?: string;
  className?: string;
  autoComplete?: string;
  minLength?: number;
  pattern?: string;
  inputMode?: "decimal" | "numeric" | "text";
}) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {(p) => (
        <input
          {...p}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          required={required}
          list={list}
          autoComplete={autoComplete}
          minLength={minLength}
          pattern={pattern}
          inputMode={inputMode}
          step={type === "number" ? "any" : undefined}
        />
      )}
    </Field>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  hint,
  required,
  minLength,
  className,
  code,
  rows,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: ReactNode;
  required?: boolean;
  minLength?: number;
  className?: string;
  code?: boolean;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(p) => (
        <textarea
          {...p}
          className={code ? "code" : undefined}
          value={value}
          rows={rows}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          required={required}
          minLength={minLength}
          spellCheck={code ? false : undefined}
        />
      )}
    </Field>
  );
}

/** Mandatory justification/reason textarea (backend requires ≥ 5 characters). */
export function ReasonField({ value, onChange, label = "Reason (mandatory, recorded in the audit trail)", min = 5 }: { value: string; onChange: (v: string) => void; label?: string; min?: number }) {
  const short = value.trim().length > 0 && value.trim().length < min;
  return (
    <Field label={label} hint={`At least ${min} characters.`} error={short ? `Please give at least ${min} characters.` : null}>
      {(p) => <textarea {...p} value={value} onChange={(e) => onChange(e.target.value)} required minLength={min} rows={2} />}
    </Field>
  );
}

export function reasonOk(v: string, min = 5): boolean {
  return v.trim().length >= min;
}

/* ------------------------------------------------------------------ layout */

export function PageHead({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, pad = true, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; pad?: boolean; className?: string }) {
  return (
    <section className={`card ${className ?? ""}`}>
      {(title || actions) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {actions}
        </div>
      )}
      <div className={pad ? "card-body" : undefined}>{children}</div>
    </section>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          id={`tab-${t.id}`}
          aria-selected={value === t.id}
          aria-controls={value === t.id ? `panel-${t.id}` : undefined}
          tabIndex={value === t.id ? 0 : -1}
          className="tab"
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const next = (i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
            const nt = tabs[next];
            if (nt) {
              onChange(nt.id);
              refs.current[next]?.focus();
            }
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  );
}

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return <div className="pagination">{total} result{total === 1 ? "" : "s"}</div>;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span>
        {from}–{to} of {total}
      </span>
      <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Previous
      </button>
      <button type="button" className="btn btn-sm" disabled={to >= total} onClick={() => onChange(offset + limit)}>
        Next
      </button>
    </nav>
  );
}

export function Hash({ value, label }: { value: string | null | undefined; label?: string }) {
  if (!value) return <span className="muted">—</span>;
  return (
    <span className="hash" title={value} aria-label={label ? `${label}: ${value}` : undefined}>
      {value}
    </span>
  );
}

export function JsonBlock({ value, summary = "Raw JSON" }: { value: unknown; summary?: string }) {
  return (
    <details>
      <summary className="small">{summary}</summary>
      <pre className="json">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

/** Notice shown in place of a screen when the user lacks the permission. The server enforces this regardless. */
export function NoAccess({ permission }: { permission: string }) {
  return (
    <Notice tone="warn" title="Not available for your role">
      This screen requires the <code>{permission}</code> permission. Access is enforced by the server and denied attempts are recorded in the audit log.
    </Notice>
  );
}
