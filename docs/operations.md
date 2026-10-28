# Operations and integration guide

## Components

| Component | Command | Notes |
|---|---|---|
| API | `uvicorn ngsirs_api.main:app` | Stateless; scale horizontally. `/healthz`, `/readyz`. |
| Worker | `celery -A ngsirs_api.worker worker --beat` | Nightly evaluation (02:17 WAT) of the trailing 12 periods. |
| Migrations | `ngsirs migrate` | Runs as `ngsirs_owner`; the API runs as `ngsirs_app`. |
| Web | `pnpm --filter ./apps/web start` | Needs `NEXT_PUBLIC_API_URL`. |

Configuration is environment-based (`NGSIRS_*`, see `apps/api/ngsirs_api/config.py`). Logs are JSON with a
`trace_id` that is also returned in `X-Trace-Id` and in every error body. Set
`NGSIRS_OTEL_EXPORTER_ENDPOINT` to export traces (collector config in `infra/otel`, which drops request
bodies and hashes user ids).

## Loading NGSIRS data

1. Register the data source (owner, data-sharing basis, permitted purpose, freshness SLA). External
   sources stay disabled until a basis is recorded.
2. Download the feed template (`GET /api/v1/imports/templates`) and map source columns if they differ
   (`field_mapping` JSON on upload).
3. Upload with `extracted_at` (with timezone) and, for complete extracts, `coverage_from`/`coverage_to`
   (and `coverage_lga` for partial extracts). **Coverage is what allows the engine to treat a missing
   record as missing**: omit it for partial or incremental files.
4. Review the preview (`/imports/{id}`, `/quality`, `/rows`), then commit. Roll back with a reason if
   needed; superseded rows are restored exactly.
5. Resolve quarantined rows and pending identity matches in the data-quality queues.
6. Run an evaluation (`POST /api/v1/rules/evaluations` with `as_of` = the extract cut-off) or let the
   nightly job run.

Load order for a fresh tenant: taxpayers -> employers -> obligations -> extensions -> returns -> payments
-> assessments (`fixtures/ngsirs/manifest.json` shows a complete example).

## API conventions

- `Authorization: Bearer <OIDC token>` on every call.
- `Idempotency-Key` on POSTs that create things (imports, evaluations, cases, case actions, reviews).
- `expected_version` in mutation bodies; a stale version returns 409 with the current version.
- `X-Purpose` for evidence export, CSV export and identifier reveal.
- Errors: `{"error": {"code", "message", "details", "trace_id"}}` with 400/401/403/404/409/422/429.
- The OpenAPI document is generated (`ngsirs export-openapi`) and CI fails if it drifts.

## Rollout gates (Tech Spec section 19)

| Gate | What to check in this platform |
|---|---|
| A | Data sources registered with lawful basis; coverage and denominators correct on the dashboard |
| B | Every obligation version approved by NGSIRS legal; rules re-approved against them |
| C | Shadow-mode sample reviewed (`operating_mode: shadow` blocks outward actions); false-positive and missingness reports approved |
| D | Limited case workflow with human approval; `outbound_messaging_enabled` only after sign-off |
| E | Security review, restore test, audit chain verification (`/audit-events/verify`), user acceptance |
| F | Programme evaluations comparing baseline and pilot outcomes |

## Disaster recovery (preliminary targets: RPO <= 24h, RTO <= 8h)

Back up PostgreSQL (PITR) and the object store; both are needed (snapshots and evidence packets live in
the object store). After a restore, run `GET /api/v1/audit-events/verify` and `POST
/api/v1/rules/evaluations/{latest}/reproduce` to prove integrity. Keys (data, token, signing) must be
restorable from the vault or encrypted data is unrecoverable.

## Performance

`scripts/benchmark_engine.py` measures engine throughput (about 160,000 rule evaluations per second on
a 4-vCPU container). NFR-02/03 must be confirmed on agreed deployment sizing with representative data
during shadow mode.
