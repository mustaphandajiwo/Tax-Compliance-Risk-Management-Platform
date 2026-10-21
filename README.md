# TaxCRIS — Integrated Compliance Risk Management & Intelligence Platform

A compliance intelligence platform for Nigerian State Internal Revenue Services (reference pilot:
**Niger State**). It connects read-only to existing revenue systems and does four things: it
reconciles taxpayer, obligation, return and payment data; it raises explainable risk indicators;
it routes cases through approval and closure with a human deciding each step; and it publishes
compliance metrics that anyone can reproduce.

> **It never makes an autonomous adverse decision.** A risk signal is something a person needs to
> review. It is not proof of evasion. TaxCRIS does not assess tax, issue penalties or replace
> statutory processes.

This repository is the MVP's first vertical slice from the PRD (`docs/prd/`, v1.0, 21 Oct 2026):
**login → synthetic taxpayer import → taxpayer profile → obligation → risk signal → analyst review
→ approved case → dashboard metric**, covering the P0 requirements FR-01 to FR-10.

## Repository layout (PRD §21)

| Path | What |
|---|---|
| `apps/api` | FastAPI modular monolith (`taxcris` package): domain engines, REST API, Alembic migrations |
| `apps/web` | Next.js + TypeScript web app (role-aware screens 01–10) |
| `workers/ingestion`, `workers/risk` | Separately scalable background workers that use the shared DB job queue |
| `packages/contracts` | OpenAPI 3.x contract (`openapi.json`) and generated TypeScript types |
| `fixtures/synthetic` | Deterministic, **fictional** Niger State dataset and its generator |
| `tests/acceptance` | Journey and control tests mapped to PRD §16 |
| `infra` | Dockerfiles, docker-compose, CI lives in `.github/workflows` |
| `docs` | ADRs, data contracts, threat model, decision log, traceability, screenshots |

## Quick start (local, no Docker)

```bash
# API
cd apps/api
uv venv .venv && uv pip install -p .venv -e ".[dev]"     # or: python -m venv .venv && pip install -e ".[dev]"
export TAXCRIS_AS_OF=2026-10-21                           # pins "today" so the demo is reproducible
export TAXCRIS_DATABASE_URL=sqlite:///./taxcris-dev.db    # or a PostgreSQL URL (recommended)
.venv/bin/taxcris-seed --reset                            # loads the synthetic pilot + a second demo tenant
.venv/bin/uvicorn taxcris.main:app --port 8000            # API docs at http://localhost:8000/docs

# Web
cd apps/web && npm install && npm run dev                 # http://localhost:3000
```

With PostgreSQL, run `alembic upgrade head` before seeding. The seed works with both.

**Docker:** `docker compose -f infra/docker-compose.yml up --build` starts PostgreSQL, migrations
and seed, the API, both workers and the web app.

### Demo accounts (synthetic tenant only)

Password for every account: `Demo-Pass-2026!` · Domain: `@niger.taxcris.test` (second tenant: `@kwara.taxcris.test`)

| User | Role | Try |
|---|---|---|
| `analyst` / `analyst2` | Risk analyst | Workbench: inspect an alert, reproduce its score, confirm it, open a case |
| `manager` / `manager2` | Compliance manager | Approve or return proposals, refer to audit, close cases |
| `officer` / `officer2` | Compliance officer | Work assigned cases and record contact |
| `audit` | Audit manager | Approve or reject audit referrals (a reason is required) |
| `steward` / `steward2` | Data steward | Quarantine, reprocessing, four-eyes merges and rollback |
| `legal` / `legal2` | Legal/policy officer | Versioned legal catalogue with two-person approval |
| `exec` | Executive | Aggregate dashboards and management brief only |
| `security` | Security auditor | Audit trail, denied-access events, hash-chain verification |
| `admin` | State administrator | Users, role matrix, tenant configuration |

Where an action needs four eyes, the second account (`…2`) is there so you can show it.

## Tests

```bash
cd apps/api
.venv/bin/pytest                                         # unit + acceptance on in-memory SQLite (~20 s)
TAXCRIS_TEST_DATABASE_URL=postgresql+psycopg://taxcris:taxcris@localhost:5432/taxcris_test .venv/bin/pytest
```

The suites cover the PRD §16 release criteria: data reconciliation (no silent loss), legal
correctness with historical rule versions, score reproducibility across the full pilot fixture,
denial of unauthorised workflow transitions, cross-tenant isolation, four-eyes controls, export
masking, and detection of audit-log tampering. The mapping is in `docs/traceability.md`.

## How it works (one paragraph)

Source batches land unchanged in an immutable landing zone (`import_records`). Each record ends up
in exactly one state: *accepted*, *rejected*, *duplicate* or *quarantined*. Identifiers are stored
only as tenant-salted HMACs. Approved, effective-dated `LegalRule` versions generate obligations, so
a 2025 period is always judged under the 2025 rule. For each taxpayer, a risk run freezes a JSON
snapshot of every input and evaluates it with a **pure function**. The function produces signals
for four dimensions (registration, filing, reporting, payment), each with severity, confidence,
exposure, evidence links and safeguard checks. Non-applicable dimensions are dropped and the
remaining weights renormalised. Data confidence is scored separately. If it is too low, or the
taxpayer is a likely unresolved duplicate, the assessment is routed to data verification instead
of becoming an adverse alert. Analysts triage alerts, giving a reason each time. Cases then move
through a permission-checked state machine in which every consequential step is approved by a
different person. Every action, view, export and denial is written to a per-tenant hash-chained
audit log, which PostgreSQL also enforces as append-only.

## Status and caveats

This is product and engineering work for validation. It is not a legal opinion. The legal rule
citations, weights (15/25/35/25), thresholds and the illustrative PAYE/DA rates in the fixture are
**placeholders**. Tax counsel must sign them off, and they must be back-tested before any pilot
use (`docs/decision-log.md`). All data in this repository is synthetic.
