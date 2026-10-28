# 0006 Authentication and authorisation

**Status:** accepted

## Decision
- OIDC bearer tokens (RS256) verified against the IdP JWKS (Keycloak realm provided in `infra/keycloak`).
  Required claims: `sub`, `tenant` (and optionally `tenant_id`), `roles`, `purposes`; `amr` must include
  `mfa` when `NGSIRS_REQUIRE_MFA=true`.
- Demo/test environments may use a built-in development issuer that signs with a local key and goes
  through the same verification. Production refuses to start with the dev issuer, demo keys, no JWKS or MFA
  disabled.
- RBAC is deny-by-default (`security/rbac.py`). Purpose-based checks (`X-Purpose`) gate evidence export,
  CSV report export and identifier reveal; the purpose is written to the audit event.
- Segregation of duties is enforced in the services: case creator != approver; rule author != either
  approver; two different people for the legal and compliance approvals; legal drafter != approver;
  programme creator != approver.
