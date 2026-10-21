# Threat model (STRIDE, MVP scope)

**Assets:** confidential taxpayer records and identifiers; risk scores and their explanations (which
must not leak to taxpayers, FR-13); case decisions; the legal-rule and risk-model configuration; the
audit trail.

**Trust boundaries:** browser ↔ API; API ↔ database; source systems → ingestion; tenant ↔ tenant;
operators/DBAs ↔ data.

| # | Threat | STRIDE | Mitigation in this codebase | Residual / next step |
|---|---|---|---|---|
| T1 | Stolen or replayed token | S | Short-lived JWT; role and active flag re-read from the DB on each request; login throttling; failed logins audited | OIDC + MFA for privileged roles (ADR-0005); refresh-token rotation |
| T2 | User reads another state's taxpayers | I | Tenant taken from the principal only; `get_scoped` returns 404; per-tenant HMAC salts; acceptance tests | PostgreSQL RLS as a second layer (D-05) |
| T3 | Insider browses records without need | I, R | Every taxpayer view, search, assessment view and export is audited with actor and role | Unusual-access detection job; periodic access recertification |
| T4 | Bulk exfiltration through exports | I | Record exports need `exports.records`, are masked and capped at 10k rows, and are audited; executives get aggregates only; denied attempts audited | Watermarking; export approval for more than N rows |
| T5 | One person pushes a merge, rule or audit through alone | E, T | Four-eyes checks in the domain layer for merges, legal rules, risk models, case proposals and audit referrals; denials audited | — |
| T6 | Audit log rewritten to hide activity | T, R | Per-tenant SHA-256 hash chain, verification endpoint, PostgreSQL trigger makes `audit_events` append-only | Ship chain heads periodically to external WORM storage |
| T7 | Malicious or poisoned source batch | T | Raw landing kept unchanged with a hash; schema validation; quarantine for unlinkable rows; checksum and idempotency key | Connector authentication (mTLS or signed uploads); malware scanning for file uploads |
| T8 | Sensitive values in logs or errors | I | Identifiers never stored in clear; generic 500 handler; audit `details` carry no raw identifiers | Log scrubbing in the gateway; DLP review |
| T9 | Score used as proof or as an automatic sanction | E (policy) | No endpoint issues notices or penalties; confidence gates; `REP-001` flagged as a hypothesis; referrals need a materiality statement and a second decision | Operating procedures and training (PRD §19) |
| T10 | Biased or unfair targeting | – | Explainable signals with safeguards; dismissals recorded with reasons for later review | Quarterly segment-disparity and false-positive evaluation (PRD §14) |
| T11 | Prompt injection via imported documents (P1 AI) | T, E | Not in scope: no AI assistant in the MVP | Design in PRD §15 before P1 |
| T12 | Denial of service via oversized imports | D | Batch limit of 50k records; jobs run asynchronously | Gateway rate limits and request size caps |
| T13 | Leaked secrets | I | Settings come from the environment; no secrets committed except the dev placeholder JWT key | Vault integration; secret scanning in CI |

Open security work for the pilot (PRD §9): encryption at rest (managed PostgreSQL and object
storage), a centralised KMS, vulnerability scanning, an independent penetration test, and a tested
backup restore (RPO ≤ 24 h, RTO ≤ 8 h).
