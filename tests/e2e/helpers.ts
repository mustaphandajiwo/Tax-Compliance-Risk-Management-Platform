import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export const RISK_LABEL = "Risk indicator, not finding of evasion";

const tokens = new Map<string, string>();

export async function token(username: string): Promise<string> {
  const cached = tokens.get(username);
  if (cached) return cached;
  const res = await fetch(`${API_URL}/api/v1/auth/dev-token`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) throw new Error(`dev-token for ${username}: HTTP ${res.status}`);
  const t = ((await res.json()) as { access_token: string }).access_token;
  tokens.set(username, t);
  return t;
}

export async function apiCall<T = unknown>(
  username: string,
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<{ status: number; data: T }> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    method,
    headers: { Authorization: `Bearer ${await token(username)}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: res.status, data: (await res.json()) as T };
}

/** Sign in through the demo login screen. */
export async function login(page: Page, username: string) {
  await page.goto("/login");
  await expect(page.getByText("SYNTHETIC DEMO", { exact: false }).first()).toBeVisible();
  await page.getByRole("radio", { name: new RegExp(`\\b${username.replace(/\./g, "\\.")}\\b`) }).check();
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/dashboard$/);
  await expect(page.getByRole("banner")).toContainText("NGSIRS Compliance Risk Management Platform");
}

interface FindingRow {
  finding_id: string;
  status: string;
  signal_class: string;
  treatment: string | null;
  flags: Record<string, boolean>;
  holds: string[];
  case: { stage: string } | null;
}

const MANAGER_APPROVED_TREATMENTS = new Set([
  "review_then_approved_reminder",
  "targeted_assistance",
  "compliance_engagement",
  "payment_engagement",
  "desk_clarification",
]);

/**
 * Findings that a compliance manager can approve a case for and that have no active case yet.
 * The database persists between runs, so tests always pick fresh ones.
 */
export async function freeFindings(count: number): Promise<string[]> {
  const { data } = await apiCall<{ items: FindingRow[] }>(
    "compliance.officer",
    "GET",
    "/risks?hold=none&page_size=500",
  );
  const ids = data.items
    .filter(
      (f) =>
        ["review_required", "approved_for_treatment"].includes(f.status) &&
        f.signal_class === "taxpayer_risk" &&
        f.treatment !== null &&
        MANAGER_APPROVED_TREATMENTS.has(f.treatment) &&
        f.holds.length === 0 &&
        (!f.case || ["closed", "rejected"].includes(f.case.stage)),
    )
    .map((f) => f.finding_id);
  if (ids.length < count)
    throw new Error(`Need ${count} findings without an active case; only ${ids.length} left. Re-seed the API.`);
  return ids.slice(0, count);
}

/** Fail on serious or critical WCAG 2.x A/AA violations. */
export async function expectAccessible(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const report = blocking
    .map(
      (v) =>
        `${v.impact} ${v.id}: ${v.help}\n  ${v.nodes
          .slice(0, 5)
          .map((n) => n.target.join(" "))
          .join("\n  ")}`,
    )
    .join("\n");
  expect(blocking, `${context} has accessibility violations:\n${report}`).toEqual([]);
}
