# 0003 Tenancy and isolation

**Status:** accepted

## Context
The PRD requires tenant isolation on every request and cross-state denial tests. PRD section 19 and
Tech Spec section 23 require that no state other than NGSIRS appears in the interface, seed data or
acceptance tests.

## Decision
- NGSIRS is the only tenant the application seeds. A test-only organisation (`is_test_only = true`) is
  created exclusively inside `tests/integration/conftest.py` to prove isolation.
- Every tenant-scoped table has `tenant_id` and a **forced** row-level-security policy on
  `current_setting('app.tenant_id')`. The application connects as `ngsirs_app` (NOBYPASSRLS); migrations run
  as `ngsirs_owner`. The tenant id is bound per transaction from the verified token.
- Application code still filters explicitly (defence in depth). Unknown or foreign ids return the same
  404 as missing ones (no existence leak).
- Within NGSIRS, officers may be LGA-scoped via the `lga_scope` claim.

## Consequences
A query that forgets a tenant filter returns nothing rather than another tenant's data. A test fails if
any table with `tenant_id` lacks a forced policy.
