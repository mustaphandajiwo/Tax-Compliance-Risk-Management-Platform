# ADR-0003: PostgreSQL-backed job queue instead of Celery/Redis at MVP

- Status: Accepted · Date: 2026-10-21

## Context
PRD §11 suggests Celery + Redis or a managed queue for idempotent import, scoring and notification
jobs. At pilot volume (tens of thousands of records per batch, a few risk runs a day), running and
securing another stateful service costs more than it gives.

## Decision
- A `jobs` table, claimed with `SELECT … FOR UPDATE SKIP LOCKED`, up to 3 attempts, then `dead`.
- Handlers are idempotent. Re-processing a batch skips rows that are not `pending`, and obligation
  generation upserts.
- `TAXCRIS_INLINE_JOBS=true` (dev/test) runs a job right after the enqueueing transaction commits.
  Production sets it to `false` and runs the `taxcris-worker --queue ingestion|risk` processes.

## Consequences
- No extra infrastructure, and jobs are transactionally consistent with the data they create.
- The `enqueue`/`dispatch` interface is narrow, so moving to Celery or a managed queue later is
  contained.
