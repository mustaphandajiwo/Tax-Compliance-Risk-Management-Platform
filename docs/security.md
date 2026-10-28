# Security, privacy and governance model

Maps Tech Spec section 14 controls to the implementation. Items marked **deployment** must be provided by
the hosting environment and are not something this repository can guarantee.

| Control | Implementation |
|---|---|
| Isolation | Forced Postgres RLS on every tenant table; app role without BYPASSRLS; tenant bound per transaction from the verified token; explicit filters as defence in depth; 404 on foreign ids. Tests: `test_20_security.py`. |
| Authentication | OIDC RS256 tokens verified against JWKS; MFA (`amr` contains `mfa`) enforced when `NGSIRS_REQUIRE_MFA=true`; production refuses to start with the dev issuer, demo keys, missing JWKS or MFA off. Keycloak realm in `infra/keycloak` (TOTP required action, PKCE public client, audience mapper). Short-lived tokens (15 min in the realm). |
| Authorisation | Deny-by-default RBAC (`security/rbac.py`); purpose-based checks via `X-Purpose` for evidence export, CSV export and identifier reveal; LGA scoping; segregation of duties in services. |
| Encryption | AES-256-GCM for identifiers (bound to the taxpayer id as associated data) and for every stored object (raw files, snapshots, evidence packets); HMAC-SHA256 tokens for matching without decryption; TLS and managed at-rest encryption are **deployment**. Keys are injected by environment/vault; rotation is **deployment** (ciphertexts carry a version byte to support re-keying). |
| Audit | Append-only `audit_event` (trigger + revoked UPDATE/DELETE) with a per-tenant SHA-256 hash chain; `GET /audit-events/verify` detects edits, gaps and reordering. Events cover rule/legal changes, approvals, overrides, reviews, case actions, imports, evaluations, evidence exports, identifier reveals and finding/taxpayer detail views. Alerting on mass export is **deployment** (events are emitted; wire them to the SIEM). |
| Integrity | Approved rule and legal versions are immutable at the database level; rule approvals and evidence packets are Ed25519-signed; import manifests are signed. |
| Privacy | Data minimisation in evidence (references plus the specific field values used); identifiers masked in the UI; reveal requires a purpose and is audited; synthetic data only in demo; external sources disabled unless a data-sharing basis is recorded. Retention periods are registered per data class; **the automated deletion job is not built** and must be added with NGSIRS's approved schedule. |
| Human oversight | No code path can issue an assessment, penalty, notice, levy or sanction. Outward contact requires an approved case, an approved template and a finding free of holds, disputes and identity doubts; demo environments never send. |
| Input safety | Restricted rule DSL (no code), parameterised SQL via SQLAlchemy, strict Pydantic request models (`extra=forbid`), upload size limit, CSV/XLSX only, object keys confined to the storage root. |
| Transport & headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, narrow CORS; TLS termination is **deployment**. |
| Rate limiting | Per-client sliding window in the API process; use the API gateway for a shared limit in production. |
| AI | None. No model participates in obligations, scoring or decisions (PRD MVP scope). |

## Threats explicitly tested

- Cross-tenant read via API (foreign finding id, forged tenant claim) and via database session.
- Cross-tenant write through the ORM.
- Expired, tampered and role-less tokens; missing MFA.
- Editing approved rule versions; updating or deleting audit events; superuser tampering with the chain.
- Self-approval of cases, rules, legal versions and programmes; one person giving both rule approvals.
- Outward contact on data-hold, legal-hold and identity-retracted cases.

## Before production (owner: NGSIRS ICT / security)

Penetration test; key management and rotation in the state vault; TLS everywhere including database
connections; backups encrypted and restore rehearsed (RPO <= 24h, RTO <= 8h preliminary); SIEM integration
for audit and access logs; hosting and data-residency approval; DPIA under the applicable Nigerian data
protection regime.
