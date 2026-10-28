# Requirements traceability and acceptance walkthrough

Status legend: **Done** = implemented and covered by an automated test; **Partial** = implemented with a
stated limitation; **Not built** = outside this delivery (reason given).

## Functional requirements (PRD section 8)

| ID | Pri | Requirement | Status | Where / evidence |
|---|---|---|---|---|
| FR-001 | P0 | CSV/XLSX/API import, mapping, validation, preview, rollback | Done: file upload, JSON push API, scheduled pull connector and signed webhooks (`docs/integrations.md`, `test_40_integrations.py`) | `services/importer`, `services/imports.py`; `test_90_import_lifecycle.py`, `test_importer_and_legal.py` |
| FR-002 | P0 | Tenant isolation everywhere | Done for DB, API, jobs. No shared cache holds tenant data | Forced RLS (`0002` migration); `test_20_security.py` |
| FR-003 | P0 | Obligation calendar by tax, category, period, effective date | Done (PAYE) | `services/legal.py`, `period_schedule`; legal transition tests |
| FR-004 | P0 | Provenance, extraction time, sharing basis, lineage | Done | `ingest_batch` (signed manifest), `source_record`, `data_source`; evidence refs on findings |
| FR-005 | P0 | Deterministic matching first; probabilistic only with approved threshold | Done | `services/identity.py` |
| FR-006 | P0 | Quarantine invalid/disputed matches; no automatic adverse release | Done | Import quarantine, identity gate; acceptance tests |
| FR-007 | P0 | Versioned rule registry, maker-checker, sandbox tests | Done | `services/rules.py`, DB immutability trigger; `test_rule_change_is_governed...` |
| FR-008 | P0 | Separate registration/filing/reporting/payment signals | Done for filing, payment, data quality (registration/reporting rules are R1) | Rule `domain` + `signal_class` |
| FR-009 | P0 | Explanation with facts, versions, effective dates | Done | `GET /risks/{id}`, `/explanation`; `test_every_finding_is_explainable...` |
| FR-010 | P0 | L, C, confidence, effort recorded separately | Done | `risk_finding` columns; scoring tests |
| FR-011 | P0 | Unknown vs non-compliant vs verified no-obligation | Done | Tri-state eligibility; `test_no_obligation_is_distinguished` |
| FR-012 | P0 | Review queue + full case audit trail with explicit decisions | Done | `finding_event`, `case_action`, `audit_event` |
| FR-013 | P0 | Correction, rebuttal, suppression, reversal | Done | Review decisions; identity retraction; auto-withdrawal when condition clears |
| FR-014 | P0 | Denominators and coverage caveats on dashboards | Done | `services/analytics.py` metric contract |
| FR-015 | P0 | Signed evidence packet export | Done (Ed25519) | `POST /cases/{id}/evidence-packet`, `/evidence-packets/verify` |
| FR-016 | P1 | Systemic risks and programmes | Partial: programmes with cohorts done; SYS rules are R1 | `services/programmes.py` |
| FR-017 | P1 | Graduated interventions with approval gates | Done | Treatment catalogue + approver roles |
| FR-018 | P1 | Record response, true/false positive, outcomes | Done | Case actions + closing outcome; false-positive metric |
| FR-019 | P1 | Backtest and compare population impact | Done | `POST /rules/versions/{id}/backtest` |
| FR-020 | P1 | State config without code change | Done | Legal versions, rules, tenant settings (thresholds, templates) |
| FR-021 | P2 | AI summarisation | Not built (R2; PRD forbids external AI in MVP) | — |
| FR-022 | P2 | Campaigns with comparison groups | Partial: deterministic comparison cohorts + diff-in-diff | `programmes` |
| FR-023 | P2 | Drift / fairness / geographic bias monitoring | Not built (R2); backtests report LGA distribution | — |
| FR-024 | P0 | Access logs, tamper-evident events, retention/deletion | Partial: hash-chained append-only audit, sensitive-read events, JSON access logs, retention policy register. **Automated deletion job not built** | `audit.py`, `retention_policy` |

## PRD section 15 acceptance tests

| Acceptance test | Test |
|---|---|
| Approved extension: FIL-001 does not fire | `test_approved_extension_prevents_fil001` |
| Return accepted before due, batch late: FIL-001 does not fire | `test_return_accepted_before_due_with_late_ingestion_does_not_fire` |
| Suspense/unallocated payment: treasury reconciliation, not non-payment | `test_suspense_payment_flags_treasury_reconciliation_not_non_payment` |
| Unverified external match: no taxpayer-facing notice | `test_unverified_match_cannot_generate_taxpayer_notice` |
| Period before January 2026 resolves correct legal version | `test_pre_2026_period_uses_prior_legal_version` |
| Changed rule: earlier score reproducible | `test_rule_change_is_governed_and_old_scores_stay_reproducible` |
| Mistaken identity link: dependent findings traceable and retractable | `test_identity_retraction_flags_dependent_findings_and_cases` |
| Manager override records actor, time, reason, previous value | `test_manager_override_records_actor_time_reason_and_previous` |
| No employee-count evidence: reporting risk unknown, not zero | `test_no_employee_count_means_reporting_risk_unknown` |
| Two tenants: users, jobs (and AI, none exists) cannot cross | `test_api_cannot_retrieve_other_tenant_records`, `test_database_session_cannot_see_other_tenant_rows`, `test_scheduled_job_is_tenant_scoped` |

## Tech Spec section 17 scenarios

| Scenario | Test / status |
|---|---|
| Accepted filing exists but extract delayed -> suppress | `test_incomplete_coverage_suppresses_missing_filing`, unit coverage tests |
| Statutory extension for one employer | golden fixture `extension_granted` |
| Unapplied receipt -> treasury flag | golden fixture `suspense_receipt` |
| Conflicting tax IDs -> quarantine, no outward action | `test_invalid_identifiers_and_periods_go_to_data_quality_queue`, DAT-001 |
| History before 01 Jan 2026 | `legal_transition` scenario |
| Rule changed after case creation | supersession test |
| Same feed uploaded twice | `test_reprocessing_same_batch_and_rules_is_idempotent`, duplicate upload |
| One state queries another -> 403/404, no leak | isolation tests (returns 404; the access log records the request, no dedicated audit event) |
| Incomplete source for denominator -> warning, rate withheld | metric contract withholds rates below 80% completeness |
| Appeal or suspension -> hold, enforcement blocked | `test_appeal_blocks_enforcement_workflow` |
| Campaign false positives high -> alert and suspension review | **Not built**: false-positive rate is shown; automatic alerting is SYS-006 (R1) |

## MVP completion criteria (PRD section 19)

| Criterion | Status |
|---|---|
| 12 PAYE-led rules on a documented synthetic fixture, reproducible | Done: 129/129 golden findings; reproduce endpoint |
| Invalid/ambiguous IDs and mismatched references -> data-quality queue | Done |
| Legal reviewer approves obligations and effective dates before activation | Done (synthetic approvals in demo, enforced by the rule approval step) |
| Case assignment, approval, suppression, override and audit logs | Done |
| Managers compare cohorts with before/after compliance and coverage | Done (programmes) |
| API contracts and frontend match the spec | OpenAPI generated + drift check in CI; generated TS client |
| No real data or external messaging from demo | Done: synthetic only; demo delivery status `not_sent_demo_environment` |

## Walkthrough (synthetic demo)

1. `uv run ngsirs demo`; start API and web; sign in as **risk.analyst** and open **Data Imports** to see
   the 10 batches, 3 quarantined rows and source freshness.
2. **Risk Register**: 129 findings. Filter `hold=data_hold` to see the 10 hard-stop items with no score.
3. Open a FIL-001 finding: trigger, evidence references, legal version, exclusions checked; press
   *Reproduce score*.
4. Sign in as **compliance.officer**, open a case on that finding; try to approve it (refused).
5. Sign in as **compliance.manager**, approve; as the officer, record a reminder with an approved template
   and see *not sent (demo environment)*.
6. As **audit.officer**, export the signed evidence packet (purpose `desk_review`) and verify it.
7. As **data.steward**, retract an identity match and watch dependent findings move to data hold.
8. As **risk.analyst**, draft a new rule version, backtest it, submit; approve as **legal.approver** and
   **compliance.manager**; activate as **compliance.manager2**; re-run the evaluation.
9. As **executive.chairman**, view the dashboard: every rate shows numerator, denominator, window and
   completeness; confirmed arrears are separated from balances under appeal.
