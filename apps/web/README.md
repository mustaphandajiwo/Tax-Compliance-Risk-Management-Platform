# TaxCRIS web (`apps/web`)

Next.js (App Router) + React + TypeScript (strict) frontend for the TaxCRIS compliance-risk platform.
It is a thin, role-aware client of the FastAPI backend in `apps/api`. The server is the security
boundary. The UI hides navigation and actions a role cannot use, but every request is authorised
server-side, and denied attempts are audited.

## Run

```bash
# 1. Backend (from apps/api). See the API docs for seeding.
TAXCRIS_AS_OF=2026-10-21 TAXCRIS_DATABASE_URL=sqlite:////tmp/t.db .venv/bin/uvicorn taxcris.main:app --port 8000

# 2. Frontend
cd apps/web
npm install
npm run dev            # http://localhost:3000 (dev)
# or production:
npm run build && npm start
```

Sign in with any demo user, e.g. `analyst@niger.taxcris.test` / `Demo-Pass-2026!`. The login page
lists every role. Users on the second tenant use `@kwara.taxcris.test`, which has an almost empty dataset.

### Environment

| Variable              | Default                 | Purpose                                                                   |
| --------------------- | ----------------------- | ------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the TaxCRIS API. Inlined at build time. The API must allow this origin via CORS. |

### Scripts

| Script                 | What it does                                                                        |
| ---------------------- | ----------------------------------------------------------------------------------- |
| `npm run dev`          | Dev server on port 3000                                                             |
| `npm run build`        | Production build (also type-checks)                                                 |
| `npm start`            | Serve the production build on port 3000                                             |
| `npm run typecheck`    | `tsc --noEmit`                                                                      |
| `npm run generate:api` | Regenerate `packages/contracts/src/api.d.ts` from `packages/contracts/openapi.json` |
| `npm run screenshots`  | Playwright acceptance screenshots → `docs/screenshots/` (see below)                 |

## API contract and typed client

`packages/contracts/openapi.json` is the contract. `openapi-typescript` generates
`packages/contracts/src/api.d.ts`; to refresh it, run `npm run fetch-spec && npm run generate` in
`packages/contracts`. `src/lib/api.ts` is a small typed fetch client. `apiGet("/v1/cases/{case_id}", { path: { case_id } })`
infers its path params, query and body from the spec, and the response type comes from the operation's 200/201/202 schema.
A few endpoints return untyped objects in the spec (metrics, data-quality summary, sandbox results);
their shapes are declared in `src/lib/types.ts`.

- The bearer token is kept in `sessionStorage`. A 401 clears it and redirects to `/login?next=…`.
- Money and decimals arrive as strings. They are only formatted for display, never used in arithmetic.
- Error `detail` from the server is shown verbatim, for example on 403 (four-eyes) and 409 (duplicate case).

## Screens

| Route                        | Who (permission)                               | What                                                                                                                                                                                                                                                                                                      |
| ---------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/login`                     | everyone                                       | Email/password; lists the demo roles                                                                                                                                                                                                                                                                          |
| `/`                          | `metrics.read` (incl. executives)              | KPI tiles showing value, numerator ÷ denominator, coverage and data date; source freshness (stale > 35 days flagged); alerts by status; timely filing by LGA (bars or table); management-brief CSV (`exports.aggregate`). Users without `metrics.read` are sent to their first permitted screen. |
| `/taxpayers`                 | `taxpayers.read`                               | Search by name/identifier, LGA, sector, type and registration                                                                                                                                                                                                                                                       |
| `/taxpayers/[id]`            | `taxpayers.read`                               | Taxpayer 360: masked identity links, employment links, obligations with status and legal rule version, filing and payment timeline with source provenance, assessments, cases. Shows a notice that access is logged.                                                                                                     |
| `/workbench`                 | `risk.read`                                    | Alert queue with filters. The evidence panel shows score, dimension contributions (score × weight; "not applicable" when null), confidence components, and signals with severity, confidence, exposure, safeguard chips, legal rule version, recommended action and evidence ref. REP-001 is labelled a hypothesis. Also shown: model version, input/output hashes, and a **Reproduce score** button. Triage (confirm/dismiss/escalate with mandatory reason) and **Open case** (409 duplicates handled). Low-confidence alerts are flagged "refer for data verification". |
| `/cases`                     | `cases.read`                                   | Filter by stage, assigned to me, SLA breached                                                                                                                                                                                                                                                                       |
| `/cases/[id]`                | `cases.read`                                   | Stage track, SLA, interventions, full action history (actor, justification, payload), assessment summary and full evidence. The action form shows only `available_actions` and asks for each action's payload plus a mandatory justification.                                                                         |
| `/audit-referrals`           | `audits.decide`                                | Referrals awaiting decision and audits in progress                                                                                                                                                                                                                                                       |
| `/data-quality`              | `imports.read` / `data_quality.review`         | Connector freshness and summary; import batches with drill-down into rejected or quarantined records and their errors; quarantine list with reprocess; merge candidates with propose/approve/reject/rollback (four-eyes); upload an import with a client-side canonical-JSON SHA-256 checksum and an idempotency key (`imports.create`). |
| `/rules`                     | `legal_rules.read` / `risk.read`               | Legal catalogue: versions, validity windows, status, citation; draft → submit → second-officer approve; retire; sandbox test. Risk model studio: weights and thresholds; draft, submit, approve, reinstate; sandbox comparison; trigger a risk run and list runs.                                                                       |
| `/audit`                     | `audit_log.read`                               | Filter audit events by action prefix, outcome (including `denied`), resource and actor; **Verify chain**                                                                                                                                                                                                                       |
| `/admin`                     | `tenant.admin` / `users.manage` / `users.read` | Tenant info, user list, create user (`users.manage`), role–permission matrix                                                                                                                                                                                                                                  |

A persistent banner reads "Synthetic demo data — fictional taxpayers". UI wording treats risk signals
as indicators for review, never as proof.

### Import checksum

The checksum is `sha256(canonical_json(records))`, where `canonical_json` matches Python's
`json.dumps(obj, sort_keys=True, separators=(",", ":"))` with `ensure_ascii=True`. Keys are sorted
recursively, there is no whitespace, and every character outside printable ASCII is escaped as `\uXXXX`.
See `src/lib/canonical.ts`. A pure-JS SHA-256 fallback covers non-secure contexts where `crypto.subtle`
is unavailable. Send money as strings (`"105000.00"`) so values hash exactly.

## Design and accessibility

- Plain CSS with variables (`src/app/globals.css`) and a small component set (`src/components/ui.tsx`),
  with no UI kit. Neutral surfaces and one deep-green accent (`#0b5e3c`, 7.9:1 against white text).
- Keyboard: skip link, visible focus rings, native buttons and inputs, labelled fields, arrow-key tabs.
  Async results are announced through `aria-live` regions.
- Works at desktop and tablet widths. Below 900 px the side navigation collapses to icons.

## Acceptance screenshots

```bash
# API on :8000 with a freshly seeded DB, web built and started on :3000
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 node scripts/screenshots.mjs
# options: WEB_URL, API_URL, CHROMIUM_PATH (default /opt/pw-browsers/chromium), SCREENSHOT_DIR, ONLY="workbench,audit log"
```

The script signs in as each role through the real login form and captures every screen at 1440×900.
It also walks one journey: the analyst confirms an open alert, opens a case and proposes a filing reminder;
the manager approves and assigns an officer, then refers another case for audit. **The journey mutates the
database, so reseed it afterwards.** It uses `playwright-core` with the preinstalled Chromium and never runs
`playwright install`.
