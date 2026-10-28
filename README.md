# NGSIRS Compliance Risk Management Platform

Compliance risk engine for **Niger State Internal Revenue Service** (Minna, Niger State, Nigeria).

It ingests NGSIRS revenue records, verifies PAYE obligations against effective-dated legal versions, detects
risk signals across filing and payment, prioritises them with transparent logic and routes them to human
review. It produces **risk indicators, not findings of evasion**, and never takes outward action on its own:
no automated assessment, penalty, notice, levy, bank action or sanction exists anywhere in the system.

> **All data in this repository is SYNTHETIC.** Identifiers look like `NGS-DEMO-EMP-0001`, names carry
> "Demo", and every legal parameter is a placeholder until NGSIRS legal officers confirm it from
> authenticated texts. Demo environments cannot send messages.

## What is here

| Path | Contents |
|---|---|
| `services/risk_engine` | Pure, deterministic engine: restricted JSON rule DSL and validator, evaluator, scoring, state machines, 12-rule NGSIRS pilot pack, reconciled 39-entry catalogue |
| `services/importer` | Feed profiles (Tech Spec section 23), CSV/XLSX parsing, row validation, quarantine decisions |
| `apps/api` | FastAPI service, SQLAlchemy models, Alembic migrations (RLS, append-only audit, immutable approved versions), CLI, Celery worker |
| `apps/web` | Next.js operations console (all PRD section 19 routes) |
| `packages/contracts` | `openapi.json` (generated) and the generated TypeScript client |
| `packages/design` | Design tokens and shared UI components |
| `fixtures/ngsirs` | Synthetic pilot fixture: 145 employers, 12 periods, 32 scenarios, `expected_findings.json` |
| `tests/` | Unit, integration (golden fixture, acceptance, security), e2e (Playwright + axe) |
| `infra/` | Dockerfiles, Compose stack (Postgres, Redis, MinIO, Keycloak, OTel), Kubernetes reference manifests |
| `docs/` | Architecture decisions, legal configuration, security model, operations, acceptance walkthrough |

## Quick start (local, synthetic data)

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), PostgreSQL 16, Node 22 + pnpm.

```bash
# 1. Database roles + database
psql -U postgres -f infra/db/init.sql
psql -U postgres -c "CREATE DATABASE ngsirs OWNER ngsirs_owner"

# 2. Backend: migrate, seed NGSIRS, load the synthetic fixture, evaluate, verify the golden file
uv sync
uv run ngsirs demo          # prints import results, run counts and the golden comparison
uv run uvicorn ngsirs_api.main:app --port 8000      # API docs at http://localhost:8000/docs

# 3. Web console
pnpm install
pnpm dev                                            # http://localhost:3000 -> pick a demo user
```

Or the whole stack in containers: `docker compose -f infra/docker-compose.yml up --build`, then
`docker compose -f infra/docker-compose.yml exec api ngsirs demo`.

### Demo users (synthetic)

| User | Role | Typical journey |
|---|---|---|
| `risk.analyst` | Risk analyst | Draft and backtest rules, investigate findings |
| `compliance.officer` | Compliance officer | Review findings, open cases, record taxpayer contact |
| `compliance.manager` / `compliance.manager2` | Compliance manager | Approve cases and rule releases, override priority, run evaluations |
| `legal.approver` | Legal / policy approver | Approve legal versions and the legal side of rule releases |
| `data.steward` / `data.steward2` | Data steward | Imports, quarantine, identity match review |
| `audit.officer` | Audit officer | Evidence packets, audit trail and chain verification |
| `executive.chairman` | Executive viewer | Aggregated dashboard and reports only |
| `field.officer.minna` | Compliance officer, LGA-scoped (Chanchaga, Bosso) | Sees only Minna findings |
| `platform.admin` | Platform administrator | Operations; cannot approve tax rules |

## Verification

```bash
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy                                            # types
uv run pytest                                          # unit + integration (needs local Postgres superuser)
uv run python -m scripts.benchmark_engine              # NFR-03 engine throughput
pnpm lint && pnpm typecheck && pnpm build             # web console + contracts + design packages
pnpm test:e2e                                          # Playwright + axe; needs API on :8000 (after `ngsirs demo`) and a prior build
```

The golden-file test loads the fixture through the real import pipeline, evaluates as at 2026-10-01 and
compares `rule_id + subject + period + status + hold` against `expected_findings.json`. The expectations
are declared per scenario in `fixtures/ngsirs/generate.py`, independently of the engine.

## Key design choices

- **Rules first, no black box.** 12 deterministic rules in a closed JSON DSL; no arbitrary code, no ML,
  no generative AI anywhere in scoring. See `docs/decisions/0002-restricted-rule-dsl.md`.
- **Unknown is not non-compliant.** A missing filing counts only when filing coverage for the period is
  complete; event time is used, never ingestion time; an obligation without an approved legal version
  is *unverified*, which becomes a hold.
- **Hard stops.** Stale data, uncertain identity, unverified obligations or undecided extensions turn a
  signal into a review / data-quality item with no culpability score. Appeals and stays keep the score
  visible but block outward action.
- **Separate dimensions.** Likelihood (1-5), consequence (1-5 or *unknown*, never guessed), confidence
  (0-1, shown separately) and effort. Priority = 4 x L x C exists only to order a queue.
- **Reproducible.** Every finding stores the rule version, legal version, tax period and input snapshot.
  `POST /api/v1/risks/{id}/reproduce` recomputes it bit-for-bit.
- **Governed change.** Rule versions need a backtest, a legal approval and a compliance-manager approval
  from two people other than the author; approved versions are immutable in the database.
- **Isolation.** NGSIRS is the only real tenant. Every tenant table carries `tenant_id` with forced
  Postgres row-level security; a test-only organisation exists only inside the test suite to prove it.

## Rule codes

The PRD and the Technical Specification used the same codes for different rules. This build adopts the
Tech Spec section 23 pilot-pack meanings and renumbers colliding PRD rules so that no code ever has two
meanings. The mapping is in `docs/legal_config/rule_catalogue.md`.

## Before production

This repository delivers a working, tested platform on synthetic data. Going live still needs the
discovery and pilot work the specification describes: NGSIRS legal sign-off of every obligation and
deadline from authenticated texts, real source extracts and data-sharing agreements, a confirmed
operational definition of "active employer", evidence-confidence thresholds set from shadow-mode profiling,
named approvers, a hosting/data-residency decision, penetration testing and a rehearsed restore. See
`docs/operations.md` and `docs/security.md`.
