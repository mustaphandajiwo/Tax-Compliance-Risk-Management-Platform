# ADR-0001: Modular monolith with separate workers

- Status: Accepted · Date: 2026-10-21

## Context
PRD §10 recommends a modular monolith for transactional services at MVP, with separate ingestion and
scoring workers and analytical storage. The pilot team is small, and the system has to be easy to
secure and operate under state-controlled hosting.

## Decision
- One Python package, `taxcris`, with domain modules (`ingestion`, `entity_resolution`, `obligations`,
  `scoring`, `cases`, `metrics`, `risk_models`) behind thin FastAPI routers.
- Background processing runs as separate processes (`workers/ingestion`, `workers/risk`) that import
  the same package. They scale and deploy on their own but share the domain code.
- Analytics are computed from PostgreSQL at MVP (`domain/metrics.py`). Marts and pre-aggregations come
  only when profiling against the pilot volume shows the <4 s p95 target needs them.

## Consequences
- One place for transactions, permission checks and audit writes, so it is simple to reason about.
- Splitting a service later is a matter of moving a domain module behind a network boundary. The
  routers already depend only on domain functions.
