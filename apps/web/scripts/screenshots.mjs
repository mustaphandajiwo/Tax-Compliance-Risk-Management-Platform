#!/usr/bin/env node
/**
 * Acceptance screenshots (PRD §21).
 *
 * Logs in as the relevant roles, captures every screen at 1440×900 into docs/screenshots/NN-name.png,
 * and walks one real journey: analyst confirms an open alert and opens a case → analyst proposes an
 * intervention → manager approves it and assigns an officer → case detail is captured.
 *
 * The journey MUTATES the demo database — reseed afterwards for a clean demo.
 *
 * Usage (web app built and running, API running):
 *   WEB_URL=http://localhost:3000 API_URL=http://localhost:8000 node scripts/screenshots.mjs
 * Env: ONLY (comma-separated step-name filter, e.g. ONLY="data quality,audit log"),
 *      CHROMIUM_PATH (default /opt/pw-browsers/chromium), SCREENSHOT_DIR (default ../../docs/screenshots)
 */
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = process.env.WEB_URL ?? "http://localhost:3000";
const API = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const OUT = process.env.SCREENSHOT_DIR ?? path.resolve(here, "../../../docs/screenshots");
const EXE = process.env.CHROMIUM_PATH ?? "/opt/pw-browsers/chromium";
const DOMAIN = "niger.taxcris.test";
const PASSWORD = "Demo-Pass-2026!";
const VIEWPORT = { width: 1440, height: 900 };

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const shots = [];
let failures = 0;

async function api(token, method, url, body) {
  const res = await fetch(API + url, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${await res.text()}`);
  return res.json();
}

async function apiToken(user) {
  const r = await api(null, "POST", "/v1/auth/login", { email: `${user}@${DOMAIN}`, password: PASSWORD });
  return r.access_token;
}

/** New isolated browser context (sessionStorage is per context) signed in through the real login form. */
async function session(user) {
  const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1, locale: "en-NG", timezoneId: "Africa/Lagos" });
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  await page.goto(`${WEB}/login`);
  await page.getByLabel("Email", { exact: true }).fill(`${user}@${DOMAIN}`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await page.locator(".topbar .user-name").waitFor();
  return { context, page };
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForFunction(() => !document.querySelector('.empty [role="status"] .spinner, [aria-busy="true"] .spinner'), null, { timeout: 15_000 }).catch(() => undefined);
  await page.waitForTimeout(250);
}

async function shot(page, name, { fullPage = false } = {}) {
  await settle(page);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage });
  shots.push(file);
  console.log(`  ✓ ${name}.png`);
}

const ONLY = (process.env.ONLY ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);

async function step(label, fn) {
  if (ONLY.length && !ONLY.some((o) => label.toLowerCase().includes(o))) return;
  console.log(`• ${label}`);
  try {
    await fn();
  } catch (e) {
    failures += 1;
    console.error(`  ✕ ${label}: ${e instanceof Error ? e.message : e}`);
  }
}

async function scrollToText(page, text) {
  await page.getByText(text, { exact: false }).first().scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -80));
}

/* ------------------------------------------------------------------ static screens */

await step("Login", async () => {
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();
  await page.goto(`${WEB}/login`);
  await page.getByText("Demo accounts").waitFor();
  await shot(page, "01-login");
  await context.close();
});

await step("Overview (executive)", async () => {
  const { context, page } = await session("exec");
  await page.goto(`${WEB}/`);
  await page.getByText("Timely filing rate").first().waitFor();
  await shot(page, "02-overview-executive");
  await scrollToText(page, "Timely filing by LGA");
  await shot(page, "03-overview-lga-breakdown");
  await context.close();
});

await step("Taxpayer search and 360 (analyst)", async () => {
  const { context, page } = await session("analyst");
  await page.goto(`${WEB}/taxpayers`);
  await page.getByLabel("Name or identifier").fill("Sabon Gari");
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: "Sabon Gari Hotels Ltd" }).waitFor();
  await shot(page, "04-taxpayer-search");
  await page.getByRole("link", { name: "Sabon Gari Hotels Ltd" }).click();
  await page.getByText("Identity links (masked)").waitFor();
  await shot(page, "05-taxpayer-360");
  await page.getByRole("tab", { name: /Filing & payment timeline/ }).click();
  await scrollToText(page, "Employment links");
  await shot(page, "06-taxpayer-360-timeline");
  await context.close();
});

await step("Workbench evidence + reproduce (analyst)", async () => {
  const { context, page } = await session("analyst");
  await page.goto(`${WEB}/workbench`);
  await page.getByRole("button", { name: /^Open evidence for/ }).first().waitFor();
  await shot(page, "07-workbench-queue");
  // Show a multi-dimension example: alerts with an under-payment signal
  await page.getByLabel("Reason code").selectOption("PAY-001");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: /^Open evidence for/ }).first().click();
  await page.getByText("Score composition").waitFor();
  await page.getByRole("heading", { name: "Evidence panel" }).evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 16));
  await shot(page, "08-workbench-evidence");
  await scrollToText(page, "Signals (");
  await shot(page, "09-workbench-signals-safeguards");
  await page.getByRole("button", { name: "Reproduce score" }).click();
  await page.getByText(/Reproducible|NOT reproducible/).waitFor();
  await scrollToText(page, "Provenance & reproducibility");
  await shot(page, "10-workbench-reproduce");
  // REP-001 is a hypothesis, labelled as such
  await page.getByLabel("Status", { exact: true }).selectOption("");
  await page.getByLabel("Reason code").selectOption("REP-001");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.waitForTimeout(600);
  const repRows = page.getByRole("button", { name: /^Open evidence for/ });
  if ((await repRows.count()) > 0) {
    await repRows.first().click();
    await page.getByText("Score composition").waitFor();
    await scrollToText(page, "Signals (");
    await shot(page, "11-workbench-hypothesis-signal");
  }
  await page.getByLabel("Reason code").selectOption("");
  // Low-confidence (suppressed) alert is visibly distinguished
  await page.getByLabel("Status", { exact: true }).selectOption("data_verification");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: /^Open evidence for/ }).first().click();
  await page.getByText("Low confidence — refer for data verification").first().waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "12-workbench-low-confidence");
  await context.close();
});

/* ------------------------------------------------------------------ journey */

let journeyCaseId = null;

await step("Journey: analyst confirms an open alert and opens a case", async () => {
  const token = await apiToken("analyst");
  const [alerts, cases] = await Promise.all([api(token, "GET", "/v1/alerts?status=open&limit=20"), api(token, "GET", "/v1/cases?limit=200")]);
  const busy = new Set(cases.items.filter((c) => c.status !== "closed").map((c) => c.taxpayer_id));
  const index = alerts.items.findIndex((a) => !busy.has(a.taxpayer_id));
  if (index < 0) throw new Error("No open alert without an existing open case");
  const target = alerts.items[index];
  console.log(`  alert for ${target.taxpayer_name} (${target.tax_type} ${target.period})`);

  const { context, page } = await session("analyst");
  await page.goto(`${WEB}/workbench`);
  await page.getByRole("button", { name: /^Open evidence for/ }).nth(index).click();
  await page.getByText("Score composition").waitFor();
  await page.getByLabel("Confirm for follow-up").check();
  await page.getByLabel("Reason (mandatory, recorded in the audit trail)").fill("Evidence reviewed: deadlines passed, feeds fresh, no extension on record");
  await page.getByRole("button", { name: "Record decision" }).click();
  await page.getByText("Alert confirmed").waitFor();
  await page.getByLabel("Case justification (mandatory)").fill("Repeated non-filing across several months merits a proportionate first step");
  await page.getByRole("button", { name: "Open case" }).click();
  await page.getByText("Case opened").waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "13-journey-alert-confirmed-case-opened");

  await page.getByRole("link", { name: /^NI-\d{4}-\d+$/ }).click();
  await page.getByText("Action history").waitFor();
  journeyCaseId = page.url().split("/cases/")[1];
  await page.getByLabel("Intervention", { exact: true }).selectOption("filing_reminder");
  await page.getByLabel("Justification (mandatory, audited)").fill("Least intrusive step: reminder of the filing obligation under the legal rule in force");
  await page.getByRole("button", { name: "Submit intervention proposal" }).click();
  await page.getByText(/Case is now pending approval/).waitFor();
  await shot(page, "14-journey-proposal-submitted");
  await context.close();
});

await step("Journey: manager approves the proposal and assigns an officer", async () => {
  if (!journeyCaseId) throw new Error("No case from previous step");
  const { context, page } = await session("manager");
  await page.goto(`${WEB}/cases/${journeyCaseId}`);
  await page.getByText("Action history").waitFor();
  await page.getByLabel("Action", { exact: true }).selectOption("approve_proposal");
  const assignee = page.getByLabel("Assign to (optional)");
  await page.waitForFunction(() => document.querySelectorAll("select option").length > 3);
  await assignee.selectOption({ label: "Yakubu Jiya — Compliance officer" });
  await page.getByLabel("Justification (mandatory, audited)").fill("Evidence sufficient; a filing reminder is proportionate");
  await page.getByRole("button", { name: "Approve proposal" }).click();
  await page.getByText(/Case is now approved/).waitFor();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "15-journey-case-approved");
  await scrollToText(page, "Action history");
  await shot(page, "16-journey-case-history");

  // Manager raises an audit referral on another open case so the audit manager queue has work.
  const token = await apiToken("manager");
  const open = await api(token, "GET", "/v1/cases?status=open&limit=50");
  for (const c of open.items) {
    if (c.id === journeyCaseId) continue;
    const detail = await api(token, "GET", `/v1/cases/${c.id}`);
    if (detail.assessment.suppressed || !detail.available_actions.includes("refer_audit")) continue;
    await page.goto(`${WEB}/cases/${c.id}`);
    await page.getByText("Action history").waitFor();
    await page.getByLabel("Action", { exact: true }).selectOption("refer_audit");
    await page.getByLabel("Materiality statement").fill("Estimated exposure exceeds the desk-verification threshold across multiple periods");
    await page.getByLabel("Justification (mandatory, audited)").fill("Pattern persists after prior contact; audit manager to decide");
    await page.getByRole("button", { name: "Refer for audit / investigation" }).click();
    await page.getByText(/audit referral pending/).waitFor();
    break;
  }
  await page.goto(`${WEB}/cases`);
  await page.getByRole("link", { name: /^NI-/ }).first().waitFor();
  await shot(page, "17-cases-list");
  await context.close();
});

await step("Audit referrals (audit manager)", async () => {
  const { context, page } = await session("audit");
  await page.goto(`${WEB}/audit-referrals`);
  await page.getByText("Awaiting decision").waitFor();
  await shot(page, "18-audit-referrals");
  await context.close();
});

await step("Data quality (steward)", async () => {
  const { context, page } = await session("steward");
  await page.goto(`${WEB}/data-quality`);
  await page.getByRole("heading", { name: "Connectors" }).waitFor();
  await shot(page, "19-data-quality-summary");
  await page.getByRole("tab", { name: "Import batches" }).click();
  await page.getByRole("button", { name: /rejected records/ }).first().click();
  await page.getByText(/Records in .* batch/).waitFor();
  await page.getByText(/Records in .* batch/).scrollIntoViewIfNeeded();
  await shot(page, "20-data-quality-imports-rejected");
  await page.getByRole("tab", { name: "Quarantine" }).click();
  await page.getByRole("heading", { name: /^Quarantined records/ }).waitFor();
  await shot(page, "21-data-quality-quarantine");
  await page.getByRole("tab", { name: "Merge candidates" }).click();
  await page.locator("table.data .row-button").first().click();
  await page.getByText("Match confidence").waitFor();
  await shot(page, "22-data-quality-merge-candidates");
  await page.getByRole("tab", { name: "Upload import" }).click();
  await page.getByRole("button", { name: "Upload batch" }).click();
  await page.getByText(/Batch [0-9a-f]{8} registered/).waitFor();
  await shot(page, "23-data-quality-upload");
  await context.close();
});

await step("Legal rules (legal officer)", async () => {
  const { context, page } = await session("legal");
  await page.goto(`${WEB}/rules`);
  await page.getByRole("button", { name: "v2" }).nth(1).click();
  await page.getByText("PAYE_MONTHLY_REMITTANCE v2").waitFor();
  await shot(page, "24-rules-legal-catalogue");
  await page.getByLabel("Sandbox: test period").fill("2025-12");
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await page.getByText("Due date produced").waitFor();
  await scrollToText(page, "Sandbox: test period");
  await shot(page, "25-rules-legal-sandbox-test");
  await context.close();
});

await step("Risk model studio (analyst)", async () => {
  const { context, page } = await session("analyst");
  await page.goto(`${WEB}/rules`);
  await page.getByRole("tab", { name: "Risk model studio" }).click();
  await page.getByRole("button", { name: "v1" }).first().click();
  await page.getByRole("button", { name: "Run sandbox comparison" }).click();
  await page.getByText("Taxpayers whose flag would change").waitFor();
  await shot(page, "26-rules-model-studio");
  await scrollToText(page, "Risk runs");
  await shot(page, "27-rules-risk-runs");
  await context.close();
});

await step("Audit log (security auditor)", async () => {
  const { context, page } = await session("security");
  await page.goto(`${WEB}/audit`);
  await page.getByRole("button", { name: "Verify chain" }).click();
  await page.getByText(/Chain intact|Chain broken/).waitFor();
  await shot(page, "28-audit-log-verified");
  await page.getByLabel("Outcome", { exact: true }).selectOption("denied");
  await page.getByRole("button", { name: "Apply" }).click();
  await page.waitForTimeout(500);
  await shot(page, "29-audit-log-denied");
  await context.close();
});

await step("Administration (state admin)", async () => {
  const { context, page } = await session("admin");
  await page.goto(`${WEB}/admin`);
  await page.getByRole("heading", { name: "Role–permission matrix" }).waitFor();
  await page.getByText("Hauwa Ndayako").first().waitFor();
  await shot(page, "30-admin");
  await context.close();
});

await browser.close();
console.log(`\n${shots.length} screenshots written to ${OUT}${failures ? ` — ${failures} step(s) failed` : ""}`);
process.exit(failures ? 1 : 0);
