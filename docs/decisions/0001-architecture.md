# 0001 Architecture and stack

**Status:** accepted · **Date:** 2026-10-28

## Context
Tech Spec section 3 recommends Next.js + TypeScript, Python/FastAPI, PostgreSQL, Redis, Celery,
S3-compatible storage and OpenTelemetry, deployable both state-hosted single-tenant and centrally hosted.

## Decision
- **Pure engine package** (`services/risk_engine`): no I/O, clock or randomness. Inputs are JSON fact
  records; outputs are `Outcome` objects. This is what makes scores reproducible and lets the engine be
  unit-tested exhaustively.
- **Importer package** (`services/importer`): parsing and validation without database access.
- **API service** (`apps/api`): FastAPI, synchronous SQLAlchemy 2 + psycopg 3, Alembic. The facts builder
  is the only code that turns canonical rows into fact records.
- **Worker**: Celery for scheduled evaluations; tasks open tenant-bound sessions like requests do.
- **Object storage**: client-side AES-GCM encryption before local disk or S3/MinIO.
- **Web**: Next.js App Router with a client generated from the OpenAPI document.

## Consequences
The engine can be swapped or re-run offline against any stored snapshot. Evaluations of the pilot
fixture (1,740 employer-periods x 12 rules) take about 3 seconds end to end; the engine alone handles
100,000 employer-periods x 8 rules in about 5 seconds (`scripts/benchmark_engine.py`).
