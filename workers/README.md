# Workers

Separately deployable background processes (PRD §10 — modular monolith with separate ingestion and
scoring workers). They share the `taxcris` package from `apps/api` and claim jobs from the
database-backed queue with `SELECT … FOR UPDATE SKIP LOCKED` (see `docs/adr/0003-job-queue.md`).

| Worker | Queue | Job kinds | Notes |
|---|---|---|---|
| `ingestion/run.sh` | `ingestion` | `import.process` | Validates landed batches, links identities, finds merge candidates. Idempotent per record. |
| `risk/run.sh` | `risk` | `risk.run` | Refreshes obligations for the scope, builds frozen input snapshots, scores, raises alerts. |

```bash
export TAXCRIS_DATABASE_URL=postgresql+psycopg://taxcris:taxcris@localhost:5432/taxcris
export TAXCRIS_INLINE_JOBS=false   # API enqueues only; workers execute
workers/ingestion/run.sh            # long-running
workers/risk/run.sh --once          # drain and exit (cron / CI)
```

Failed jobs are retried up to 3 attempts, then marked `dead`; the import batch or risk run is marked
`failed` with the error so operators see it in the data-quality screen.
