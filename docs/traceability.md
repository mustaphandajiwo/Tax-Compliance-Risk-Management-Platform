# Requirements traceability (P0 scope)

| Req | Acceptance test (PRD) | Implementation | Verified by |
|---|---|---|---|
| FR-01 Import | Imports with counts, errors, lineage | `domain/ingestion.py`, `POST/GET /v1/imports`, `import_records` landing zone | `test_ingestion.py::test_batch_reconciles…`, `test_idempotent…`, `test_pilot_fixture.py` |
| FR-02 Dedupe & link | Candidates with confidence; manual merge approval | `domain/entity_resolution.py`, `/v1/merge-candidates` | `test_ingestion.py::test_duplicate_merge_requires_two_stewards_and_can_roll_back` |
| FR-03 Versioned obligations | Historical period selects correct rule version | `domain/obligations.py` (`select_rule`, `generate`), `/v1/legal-rules` | `test_obligations.py::test_historical_period_selects_rule_version_in_force` |
| FR-04 Signals | Each signal links to source and calculation | `domain/scoring.py::evaluate` (`evidence_ref`, `safeguards`, legal rule) | `test_scoring.py`, `test_first_slice.py` |
| FR-05 Explainable, reproducible scores | Reproduce score for a past run | Frozen inputs + hashes; `POST /v1/risk-assessments/{id}/reproduce` | `test_pilot_fixture.py` (all assessments), `test_first_slice.py` |
| FR-06 Alert triage | Dismiss/confirm/escalate with reason | `domain/cases.py::triage`, `POST /v1/alerts/{id}/triage` | `test_first_slice.py`, `test_controls.py::test_low_confidence…` |
| FR-07 Cases & interventions | Assignment, SLA, approvals, actions, closure logged | `domain/cases.py` state machine, `/v1/cases` | `test_first_slice.py`, `test_controls.py::test_unauthorised_and_invalid_case_transitions`, `…audit_referral_rejection…` |
| FR-08 Dashboards | Definitions, filters, freshness shown | `domain/metrics.py`, `GET /v1/metrics`, web Overview | `test_first_slice.py::test_metric_reconciles_to_source` |
| FR-09 Audit trail | Tamper-evident, searchable by auditor | `audit.py` hash chain, `/v1/audit-events(/verify)`, migration 0002 trigger | `test_audit.py` |
| FR-10 Role-based exports with masking | Denied export leaves audit record | `routers/reporting.py`, `deps.require` + `deny` | `test_controls.py::test_role_permissions_denied_and_audited`, `test_record_export_is_masked_and_logged` |

| PRD §16 criterion | Verified by |
|---|---|
| Data reconciliation, no silent loss | `test_ingestion.py`, `test_pilot_fixture.py` |
| Legal correctness (deadlines, jurisdiction, historical changes) | `test_obligations.py` |
| Scoring reproducibility | `test_scoring.py::test_evaluation_is_deterministic…`, `test_pilot_fixture.py` |
| Case workflow: unauthorised transitions denied, reasons captured | `test_controls.py`, `test_first_slice.py` |
| Access isolation: no cross-tenant access | `test_controls.py::test_no_cross_tenant_taxpayer_access` |
| Security / performance / UAT | Out of scope for the codebase. See the threat model and pilot plan |

P1/P2 items (FR-11 AI assistant, FR-12 experiments, FR-13 taxpayer portal, FR-14 training
simulator) are deliberately not built. PRD §17 puts them after a stable rules-based MVP.
