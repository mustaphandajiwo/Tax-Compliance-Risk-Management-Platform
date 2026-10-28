"use client";

import { useAuth } from "@/lib/auth";
import { useReference } from "@/lib/hooks";
import { humanize } from "@/lib/format";

/**
 * Declared purpose for sensitive reads and exports (sent as X-Purpose). Only the purposes in the
 * caller's token (/me.purposes) are offered; the API re-checks and audits the declaration.
 */
export function PurposeSelect({
  id,
  value,
  onChange,
  preferred,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  preferred?: string;
}) {
  const { me } = useAuth();
  const ref = useReference();
  const purposes = me?.purposes ?? [];
  return (
    <div className="field">
      <label htmlFor={id}>Declared purpose (recorded in the audit log)</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Choose a purpose…</option>
        {purposes.map((p) => (
          <option key={p} value={p}>
            {ref?.purposes[p] ? `${humanize(p)} — ${ref.purposes[p]}` : humanize(p)}
            {p === preferred ? " (suggested)" : ""}
          </option>
        ))}
      </select>
      {purposes.length === 0 && <p className="field__hint">Your role has no declarable purposes, so this export is unavailable.</p>}
    </div>
  );
}
