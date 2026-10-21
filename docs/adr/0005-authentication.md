# ADR-0005: Authentication — local accounts now, OIDC/SAML at pilot

- Status: Accepted (interim) · Date: 2026-10-21

## Decision
- MVP: local accounts with PBKDF2-SHA256 (240k iterations) and short-lived HS256 JWTs (8 h) whose
  role is re-read from the database on every request, so a revocation takes effect immediately.
  Logins are throttled per client and email, and every success and failure is audited.
- Pilot: an OIDC/SAML identity provider chosen with the state, with MFA mandatory for privileged roles
  (`data_steward`, `legal_officer`, `compliance_manager`, `audit_manager`, `state_admin`,
  `security_auditor`). The `Principal` abstraction in `deps.py` is the only place that has to change.
- The JWT secret comes from the secrets vault and never from the repository.
