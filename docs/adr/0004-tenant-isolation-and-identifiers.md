# ADR-0004: Tenant isolation and identifier protection

- Status: Accepted · Date: 2026-10-21

## Decision
- Every operational row has a `tenant_id`. The tenant always comes from the authenticated principal
  and never from request input. `get_scoped()` returns 404 for rows that belong to another tenant, so
  their existence is not revealed.
- Identifiers (TIN, NIN, CAC RC) are stored only as `HMAC-SHA256(tenant_salt, type:normalised_value)`
  with a masked display hint. The same TIN hashes differently in each state, so the datasets cannot
  be joined across tenants.
- Each tenant has its own audit hash chain.
- A dedicated database or instance per state is supported for higher assurance: point
  `TAXCRIS_DATABASE_URL` at a separate database for each deployment. PostgreSQL row-level security
  is the next hardening step for shared deployments (see the decision log).

## Verification
`tests/acceptance/test_controls.py::test_no_cross_tenant_taxpayer_access` and
`test_same_identifier_hashes_differ_per_tenant`.
