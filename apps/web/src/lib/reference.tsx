"use client";

import { useEffect, useState } from "react";
import { apiGet } from "./api";
import type { MetricsResponse } from "./types";

export const TAX_TYPES = ["PAYE", "DA"] as const;

/** Sector vocabulary used by the pilot connectors (suggestions only; filters accept free text). */
export const SECTORS = ["Agriculture", "Construction", "Education", "Health", "Hospitality", "ICT", "Manufacturing", "Professional services", "Retail", "Transport"];

export const ALERT_STATUSES = ["open", "data_verification", "confirmed", "escalated", "dismissed"];
export const CASE_STATUSES = ["open", "pending_approval", "approved", "in_progress", "audit_referral_pending", "audit_in_progress", "closed"];

export const INTERVENTIONS = ["no_action", "correct_data", "educational_communication", "filing_reminder", "assisted_filing", "desk_verification", "payment_follow_up"];
export const REFERRALS = ["audit_referral", "investigation_referral"];
export const CONTACT_CHANNELS = ["letter", "email", "sms", "phone", "visit", "portal"];
export const DISPOSITIONS = ["resolved_compliant", "resolved_collected", "data_corrected", "no_further_action", "referred_external", "audit_completed"];

export const ROLES = ["state_admin", "data_steward", "risk_analyst", "compliance_officer", "compliance_manager", "audit_manager", "legal_officer", "executive", "security_auditor"];

export const DIMENSIONS = ["registration", "filing", "reporting", "payment"] as const;

/** LGA names are tenant-specific; derive suggestions from the metrics breakdown when the user may read metrics. */
export function useLgaOptions(enabled: boolean): string[] {
  const [lgas, setLgas] = useState<string[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    apiGet("/v1/metrics")
      .then((r) => {
        const m = r as unknown as MetricsResponse;
        if (live) setLgas((m.breakdowns.timely_filing_by_lga ?? []).map((b) => b.lga).sort());
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [enabled]);
  return lgas;
}

export function Datalist({ id, options }: { id: string; options: string[] }) {
  return (
    <datalist id={id}>
      {options.map((o) => (
        <option key={o} value={o} />
      ))}
    </datalist>
  );
}
