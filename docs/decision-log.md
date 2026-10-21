# Decision log — open legal, privacy, data and deployment questions (PRD §21–22)

| ID | Question | Status | Owner | Notes |
|---|---|---|---|---|
| D-01 | Sponsoring SIRS and technical counterpart | Open | Product owner | Niger State is the reference pilot |
| D-02 | Approved tax types and periods for the pilot | Assumed: PAYE monthly and DA annual, 2025–2026 | Legal/policy lead | Encoded as `LegalRule` rows; not hard-coded |
| D-03 | PAYE and DA deadlines and citations under the Nigeria Tax Administration Act 2025 | **Open: placeholder** | Tax counsel | Seed v2 rules (from 2026-01-01) carry the PITA deadlines forward with placeholder citations. They must be verified before any shadow run |
| D-04 | Risk weights (15/25/35/25), alert threshold (25), minimum confidence (0.6) | **Open: placeholder** | Compliance risk specialist | PRD §6 marks them unvalidated. Back-test on 12–24 months of history before setting bands |
| D-05 | Shared database with RLS, or a dedicated database per state | Open | Architect + state ICT | The application layer already isolates tenants. A dedicated DB is supported today |
| D-06 | Hosting, data residency and procurement | Open | State procurement | Needs NDPA 2023 review; DPIA before production connectors |
| D-07 | Retention of raw landing records, superseded assessment inputs and audit events | Open | Legal + data steward | Purges of audit events must run as a separate audited DBA procedure (trigger blocks app deletes) |
| D-08 | Who approves legal rules, risk thresholds and interventions | Assumed per PRD §2 role matrix | State sponsor | Encoded in `permissions.py` and the domain four-eyes checks |
| D-09 | Inventory of actual revenue software and APIs | Open | Data engineer | Data contracts use placeholder source names |
| D-10 | Liable-population estimate for registration coverage | Open | Statistics / policy | Metric currently labelled `estimate_quality: low` |
| D-11 | Identity provider and MFA | Open | State ICT | ADR-0005 |
| D-12 | Effective tax rates in the synthetic fixture (PAYE 7 %, DA 8 %) | Synthetic only | — | Only used to generate fictional data; never used in scoring logic |
| D-13 | SLA days per intervention type | Assumed defaults in `domain/cases.py` | Compliance manager | Overridable per tenant via `tenant.config.sla_days` |
