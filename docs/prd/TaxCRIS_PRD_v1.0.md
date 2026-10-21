Integrated Compliance Risk Management & Intelligence Platform

Product Requirements Document (PRD) and Technical Architecture &
Implementation Blueprint

Designed for Nigerian State Internal Revenue Services \| Reference
pilot: Niger State

Version 1.0 • Working specification • 21 October 2026

# Executive decision summary

Build a multi-tenant-capable but logically and operationally isolated
compliance intelligence platform that connects to existing state revenue
systems. The first release targets PAYE and personal income tax
direct-assessment workflows. It identifies plausible registration,
filing, reporting and payment risks; recommends proportionate
interventions; supports human-approved case management; and measures
outcomes. It does not replace tax assessment, payment or statutory
appeal systems.

MVP acceptance gate: at least one state can ingest and reconcile
taxpayer, obligation, return and payment data; show traceable risk
indicators; route a case from detection through approval and closure;
and publish a reproducible compliance dashboard without making an
autonomous adverse decision.

# PART A \| PRODUCT REQUIREMENTS

## 1. Product boundaries and principles

-   Primary users: risk analysts, compliance officers, audit managers,
    revenue directors, executive leadership, legal administrators, data
    stewards and system administrators.

-   Secondary users (later phase): taxpayers through a separate
    self-service portal; ACTG Academy trainees through a separate
    synthetic-data environment.

-   In scope for MVP: ingest, entity resolution, obligations, rules,
    scoring, alerts, cases, interventions, approvals, dashboard, audit
    trails, exports.

-   Out of scope for MVP: automated tax assessment or penalties;
    taxpayer-facing public scores; fully autonomous audits; unrestricted
    cross-agency data collection; national tax collection; full ERP
    replacement.

-   Core principles: legal accuracy by tax period; explainability;
    evidence provenance; human oversight; privacy; measurable outcomes;
    configurable state-specific rules.

## 2. Roles and permissions

  -----------------------------------------------------------------------
  Role                    Read / action           Approval limits
                          permissions             
  ----------------------- ----------------------- -----------------------
  State administrator     Manage tenant           No authority to approve
                          configuration, users,   tax enforcement by
                          integrations; cannot    default
                          edit evidence silently  

  Data steward            Review ingestion        Approve merges under
                          exceptions, duplicates, four-eyes control
                          provenance and quality  

  Risk analyst            View authorised         Cannot approve own rule
                          profiles, configure     deployment
                          proposed risk rules,    
                          investigate alerts      

  Compliance officer      Work assigned cases,    No independent audit
                          record contact and      authorisation
                          outcomes                

  Compliance manager      Prioritise campaigns,   Approvals by state
                          approve outreach and    policy
                          desk reviews            

  Audit manager           Approve audit referrals No automatic assessment
                          and assign audit teams  

  Legal/policy officer    Maintain versioned law  Dual approval for
                          and obligation          production legal rules
                          catalogue               

  Executive               Aggregated dashboards   No unrestricted
                          and authorised          raw-data export
                          drill-down              

  Security auditor        Immutable logs and      Read-only
                          access review           
  -----------------------------------------------------------------------

## 3. Functional requirements and priorities

  ---------------------------------------------------------------------------------
  ID                Requirement        Priority          Acceptance test
  ----------------- ------------------ ----------------- --------------------------
  FR-01             Import taxpayers,  P0                Scheduled and manual
                    filings, payments,                   imports with counts,
                    employers, tax                       errors, lineage
                    types                                

  FR-02             Deduplicate and    P0                Candidate matches shown
                    link persons,                        with confidence; manual
                    entities, employer                   merge approval
                    relationships                        

  FR-03             Determine          P0                Historical period selects
                    applicable                           correct rule version
                    obligations using                    
                    versioned rules                      

  FR-04             Detect             P0                Each signal links to
                    registration,                        source and calculation
                    filing, reporting,                   
                    payment signals                      

  FR-05             Compute            P0                Reproduce score for a past
                    explainable risk                     run
                    and                                  
                    data-confidence                      
                    scores                               

  FR-06             Generate and       P0                Dismiss/confirm/escalate
                    triage risk alerts                   with reason

  FR-07             Manage             P0                Assignment, SLA,
                    interventions and                    approvals, actions and
                    cases                                closure logged

  FR-08             Executive and      P0                Metric definitions,
                    operational                          filters and freshness
                    dashboards                           shown

  FR-09             Full access and    P0                Tamper-evident events
                    decision audit                       searchable by authorised
                    trail                                auditor

  FR-10             Role-based exports P0                Denied export leaves audit
                    with masking                         record

  FR-11             Natural-language   P1                Grounded answers with
                    analytics                            source and permissions
                    assistant                            

  FR-12             Campaign           P1                Comparison cohorts and
                    experimentation                      metrics recorded
                    and outcome                          
                    evaluation                           

  FR-13             Taxpayer           P2                No disclosure of internal
                    compliance                           risk scores
                    self-check portal                    

  FR-14             Training simulator P2                Isolated from live
                    with synthetic                       taxpayer records
                    cases                                
  ---------------------------------------------------------------------------------

## 4. Core user journeys

Journey A: Compliance analyst selects a tax period and sector → reviews
data freshness and coverage → opens a risk alert → examines legal
obligation, evidence, data quality and score explanation → confirms or
dismisses → submits intervention proposal.

Journey B: Compliance manager reviews proposal → checks proportionality
and evidence → approves education/reminder/desk review or returns for
revision → assigns officer → monitors SLA → closes with recorded
outcome.

Journey C: Audit manager reviews a referred case → evaluates
materiality, evidence and available capacity → approves or rejects audit
selection → records actual audit findings and downstream outcomes. The
system never treats a risk signal as proof of evasion.

Journey D: Executive filters dashboards by LGA, sector, tax type and
period → reviews numerator, denominator, coverage and last-refresh
metadata → downloads aggregate management brief.

## 5. Screens and interaction design

  -----------------------------------------------------------------------
  Screen                              Key components
  ----------------------------------- -----------------------------------
  01 Overview                         Filing, payment and registration
                                      compliance; trend; source
                                      freshness; risk queue; intervention
                                      outcomes

  02 Taxpayer 360                     Identity links, obligations,
                                      filing/payment timeline, risks,
                                      evidence, permissions and case
                                      history

  03 Risk workbench                   Filters, saved views, priority
                                      queue, evidence panel, rule
                                      version, disposition

  04 Risk model studio                Rule authoring, test sandbox,
                                      version comparison, approval,
                                      rollback

  05 Compliance campaigns             Segment builder, treatment plan,
                                      channels, budget, outcome tracking

  06 Case management                  Case stages, officer assignments,
                                      SLA, notes, documents, approval
                                      history

  07 Audit referrals                  Audit selection rationale, queue,
                                      capacity, decisions, outcome
                                      linkage

  08 Analytics                        Tax type/sector/LGA trends, cohort
                                      comparison, definitions, confidence

  09 Data quality                     Connector status, unmapped records,
                                      matching review, stale feeds

  10 Administration                   Tenant config, users, role matrix,
                                      legal catalogue, retention,
                                      security

  11 AI assistant (P1)                Questions, SQL-safe analytic tools,
                                      citations, uncertainty and
                                      escalation
  -----------------------------------------------------------------------

## 6. Risk framework and score specification

Model risk by tax type, taxpayer segment, obligation and period, not as
one universal score. Registration, filing, reporting and payment each
produce signals with severity, confidence, potential exposure and
recommended next step. Illustrative initial weights are registration
15%, filing 25%, reporting 35% and payment 25%; these are placeholders,
not validated policy.

Score design: for each applicable dimension, compute a 0--100 rule
score; exclude non-applicable dimensions and renormalise weights.
Overall risk = sum(applicable dimension score × normalised weight).
Independently compute data-confidence (coverage, timeliness, matching
certainty and evidence reliability) and estimated revenue exposure,
where defensible. Suppress adverse automated prioritisation when
confidence is insufficient; refer for data verification.

  -----------------------------------------------------------------------
  Signal example                      Safeguard / exception
  ----------------------------------- -----------------------------------
  Required PAYE return not received   Check active employer status,
  by legal deadline                   relevant period, valid extension
                                      and feed freshness

  Payment below declared liability    Check adjustments, credits,
                                      disputes, allocations and payment
                                      reconciliation

  Material unexplained income         Flag as hypothesis; check
  deviation                           seasonality, business closure and
                                      data reliability

  Unregistered entity in authorised   Verify identity, jurisdiction and
  business dataset                    whether obligation applies
  -----------------------------------------------------------------------

Every score stores: model_version, ruleset_version, obligation_version,
evaluation_time, inputs and hashes, applicable weights, individual
signals, reason codes, confidence, reviewer actions and superseding
recalculations. Risk bands are configured only after back-testing and
approval.

## 7. Intervention decision policy

Treatment options: no action; correct data; educational communication;
filing reminder; assisted filing; desk verification; approved payment
follow-up; audit referral; investigation referral. Treatment selection
must consider materiality, confidence, previous contact, taxpayer
rights, statutory limits and staff capacity. Legal notices and sanctions
must be issued only by authorised processes and officers.

## 8. KPI definitions and evaluation

  -----------------------------------------------------------------------
  KPI                                 Definition / caution
  ----------------------------------- -----------------------------------
  Timely filing rate                  Returns filed by deadline ÷ returns
                                      legally due among eligible active
                                      taxpayers

  Payment compliance rate             Obligations paid on time ÷
                                      obligations due; distinguish count
                                      and value measures

  Registration coverage               Registered liable population ÷
                                      defensible estimated liable
                                      population; show estimate quality

  Cases resolved within SLA           Closed within defined SLA ÷ closed
                                      cases; report case mix

  Audit yield                         Collected audit-related revenue net
                                      of refunds, plus separate
                                      assessment figure

  Intervention uplift                 Difference in outcomes vs credible
                                      comparison group; show uncertainty

  Revenue at risk                     Scenario estimate with method,
                                      exclusions and confidence interval,
                                      not collectible debt
  -----------------------------------------------------------------------

## 9. Non-functional requirements

-   Availability target: 99.5% monthly for pilot, excluding planned
    maintenance; higher production SLA subject to funding.

-   Performance: 95th percentile standard dashboard response \<4 seconds
    on representative pilot dataset; background scoring asynchronous.

-   Scale: design for millions of taxpayer and obligation records,
    tested against realistic volumes before rollout.

-   Security: encryption in transit and at rest, MFA for privileged
    users, least privilege, secrets vault, vulnerability scanning and
    penetration test.

-   Recovery: proposed RPO ≤24 hours and RTO ≤8 hours for pilot, to be
    tightened by agreed service levels.

-   Accessibility: keyboard support, readable contrast and responsive
    desktop/tablet interfaces.

-   Observability: metrics, traces, alerts, connector lag, job failures
    and risk-rule drift.

-   Data residency, retention and breach procedures determined through
    legal review and state procurement requirements.

# PART B \| TECHNICAL ARCHITECTURE

## 10. Logical architecture

Source systems → secure ingestion gateway → raw immutable landing zone →
validation and normalisation → taxpayer/entity master → obligation
engine → compliance signal engine → risk and exposure engine →
case/workflow service → API gateway → web dashboards and controlled AI
assistant. All services emit audit events and observability telemetry.

Recommended deployment: modular monolith for transactional services at
MVP, with separate ingestion/scoring workers and analytical storage.
This is simpler to secure and operate than premature microservices.
Split services only where scaling or governance warrants it.

## 11. Suggested technology stack

  -----------------------------------------------------------------------
  Layer                   Suggested               Notes
                          implementation          
  ----------------------- ----------------------- -----------------------
  Frontend                Next.js / React +       Accessible component
                          TypeScript              library; role-aware
                                                  views

  Backend                 Python FastAPI or       API-first, typed
                          Django                  contracts, clear
                                                  permission checks

  Transactional database  PostgreSQL              Tenant/state isolation,
                                                  row-level controls
                                                  where appropriate

  Background tasks        Celery + Redis /        Idempotent import,
                          managed queue           scoring and
                                                  notification jobs

  Analytics               PostgreSQL marts        Pre-aggregations,
                          initially; warehouse    lineage and metric
                          later                   catalogue

  Files / evidence        Encrypted object        Versioning, malware
                          storage                 scanning and retention

  Search                  PostgreSQL full text    Dedicated search only
                          initially               when justified

  Identity                OIDC/SAML-compatible    MFA, RBAC and possible
                          identity provider       ABAC

  AI assistant (P1)       Approved LLM gateway +  No direct unrestricted
                          retrieval + bounded     SQL or autonomous
                          analytic tools          enforcement

  Infrastructure          Containers, managed     State-controlled
                          database, IaC, CI/CD    tenancy and
                                                  auditability
  -----------------------------------------------------------------------

## 12. Data model: minimum entities

  -----------------------------------------------------------------------
  Entity                              Core fields
  ----------------------------------- -----------------------------------
  Tenant / State                      tenant_id, state_code,
                                      config_version, legal_jurisdiction

  Taxpayer                            taxpayer_id, type, name,
                                      registration_status, tax_residence,
                                      source_refs

  IdentityLink                        link_id, taxpayer_id,
                                      identifier_type, hashed_identifier,
                                      match_confidence, approved_by

  TaxObligation                       obligation_id, taxpayer_id,
                                      tax_type, period, due_date,
                                      rule_version, status

  Return                              return_id, obligation_id,
                                      filing_date, reported_amount,
                                      source_system, source_record_id

  Payment                             payment_id, taxpayer_id,
                                      obligation_id, amount,
                                      payment_date, allocation_status

  RiskSignal                          signal_id, taxpayer_id,
                                      obligation_id, rule_id,
                                      evidence_ref, severity, confidence

  RiskAssessment                      assessment_id, run_id,
                                      model_version, score, confidence,
                                      exposure_estimate

  Alert / Case                        case_id, taxpayer_id, alert_id,
                                      owner, status, SLA, disposition

  Intervention                        intervention_id, case_id, type,
                                      approved_by, execution_time,
                                      outcome

  LegalRule                           rule_id, jurisdiction, tax_type,
                                      valid_from/to, approved_version

  AuditEvent                          event_id, actor, action, resource,
                                      timestamp, before_after_hash
  -----------------------------------------------------------------------

Every operational table includes tenant_id and created/updated
timestamps. Use UUID primary keys, separate source identifiers, explicit
provenance and soft-deletion/retention controls. Never assume that a
business and its owner are the same taxpayer.

## 13. Integration and ingestion contracts

Prioritise read-only connectors to existing state taxpayer registers,
PAYE returns, direct-assessment records, payments and employer
registries. Each connector has owner, legal basis, refresh cadence, data
dictionary, schema version, reconciliation totals, error handling and
revocation mechanism.

  -----------------------------------------------------------------------
  Interface                           Example contract
  ----------------------------------- -----------------------------------
  POST /v1/imports                    Register ingestion batch and
                                      checksum; async validation;
                                      idempotency key

  GET /v1/imports/{id}                Counts accepted/rejected/duplicate;
                                      lineage; reconciliation status

  GET /v1/taxpayers/{id}              Authorised taxpayer profile with
                                      masked sensitive fields

  GET /v1/risk-assessments            Filters: tax type, period, sector,
                                      LGA, confidence and status

  POST /v1/risk-runs                  Authorised rule/model version and
                                      dataset snapshot; returns job ID

  POST /v1/cases                      Create case from reviewed alert;
                                      duplicate prevention

  POST /v1/cases/{id}/actions         Workflow transition with
                                      permission, justification and audit
                                      event

  GET /v1/metrics                     Approved definitions,
                                      numerator/denominator, data
                                      freshness
  -----------------------------------------------------------------------

API standards: OpenAPI 3.x, OAuth2/OIDC, request validation, rate
limits, pagination, idempotent write semantics, signed webhooks where
used and no sensitive values in application logs.

## 14. Security, privacy and model governance

-   Conduct a data protection impact assessment and
    jurisdiction-specific legal review before production integrations.

-   Keep state data segregated: tenant-aware authorisation in
    application and database; dedicated database/instance available for
    higher assurance.

-   Encrypt backups and object storage; centralised key management;
    short-lived service credentials.

-   Log every taxpayer record access and export; implement
    unusual-access detection and periodic access recertification.

-   Require dual control for taxpayer merges, rule publication and
    high-impact case escalation.

-   AI must retrieve from approved legal and case sources, cite them
    internally, abstain when unsupported and use tool-level permissions.

-   Never train external foundation models on confidential taxpayer data
    by default; prohibit raw taxpayer data in unapproved third-party
    services.

-   Evaluate model precision, false positives, segment disparities,
    concept drift and intervention outcomes quarterly.

-   Document retention, correction, appeal and lawful sharing procedures
    before deployment.

## 15. Rule engine and AI orchestration

Represent legal obligations as declarative rules with jurisdiction, tax
type, taxpayer eligibility, effective dates, filing deadlines,
exemptions, evidence requirements and approval history. Rules execute
deterministically. AI may explain and draft, but must not silently
modify legal rules or produce binding tax conclusions.

P1 assistant flow: user query → identity/permission checks → classify
request → retrieve authorised data and versioned legal sources → invoke
constrained metrics/query services → generate explanation with source
references, dates and confidence → log request and result. Block
prompt-injection instructions found in imported documents.

## 16. Testing and acceptance plan

  -----------------------------------------------------------------------
  Test category                       Minimum release criterion
  ----------------------------------- -----------------------------------
  Data reconciliation                 100% of imported records accounted
                                      for as accepted, rejected or
                                      quarantined; no silent loss

  Legal correctness                   Approved scenario tests cover
                                      deadlines, exemptions, jurisdiction
                                      and historical changes

  Scoring reproducibility             Same frozen inputs and version
                                      produce identical results

  Case workflow                       Unauthorised transitions denied;
                                      approvals and reason captured

  Security                            No critical/high unresolved
                                      findings from independent security
                                      review

  Access isolation                    Automated tests prove no
                                      cross-tenant taxpayer access

  Performance                         Representative load tests meet
                                      agreed SLO

  User acceptance                     Pilot users complete core journeys
                                      with documented sign-off
  -----------------------------------------------------------------------

# PART C \| DELIVERY PLAN

## 17. Implementation work packages

  ------------------------------------------------------------------------
  Sprint group            Deliverables            Exit condition
  ----------------------- ----------------------- ------------------------
  0: Discovery (2--3      Process maps, data      State sponsor signs
  weeks)                  inventory, legal rules  requirements and source
                          register, baseline      inventory
                          KPIs, DPIA scope        

  1--2: Foundations (4    Auth, tenant config,    End-to-end import of
  weeks)                  ingestion framework,    synthetic data
                          schema, audit log       

  3--4: Data and rules (4 Taxpayer master,        Approved
  weeks)                  obligation engine,      PAYE/direct-assessment
                          data-quality workbench  test cases pass

  5--6: Risk and cases (4 Signals, scoring, alert Reproducible
  weeks)                  review, case workflow   risk-to-case journey

  7: Dashboards (2 weeks) Metrics, management     Validated figures
                          views, exports          reconcile to source

  8: Hardening/pilot      Security, UAT,          Signed pilot go-live
  (3--5 weeks)            training, production    checklist
                          cutover, monitoring     
  ------------------------------------------------------------------------

Estimated MVP timeline: approximately 5--6 months, subject to data
access, legal review, staffing and existing system quality. P1 AI and
experiments should follow a stable rules-based MVP.

## 18. Delivery team and responsibilities

Minimum core team: product owner with SIRS experience; tax legal/policy
lead; compliance risk specialist; technical architect/backend engineer;
frontend engineer; data engineer; QA/security support; UX designer
part-time; state data stewards and pilot users. ACTG could lead domain
design, training and evaluation, with a dedicated engineering partner
responsible for production delivery.

## 19. Pilot design: Niger State

Pilot cohort: PAYE employers and direct-assessment taxpayers, with
12--24 months of available history where lawful and reliable. Establish
baseline completeness and filing/payment metrics before scoring. Begin
with read-only data integration, run shadow risk assessments, review a
stratified sample with experienced officers, then authorise limited
interventions. Compare outcomes to matched or randomised eligible
controls where feasible.

Go/no-go criteria: verified legal rules; acceptable data quality; risk
precision and false-positive review; no critical security issues; signed
operating procedures; human approval for all consequential actions;
measurable improvement potential relative to baseline.

## 20. Risks and mitigations

  -----------------------------------------------------------------------
  Risk                                Mitigation
  ----------------------------------- -----------------------------------
  Poor or incomplete source data      Data quality scores, quarantines,
                                      manual verification and staged
                                      connectors

  Incorrect legal interpretation      Tax counsel sign-off,
                                      effective-date versioning and test
                                      library

  False positives / unfair targeting  Explainability, confidence gates,
                                      sampling review and
                                      appeal/correction paths

  Vendor lock-in                      Open APIs, exportable schemas,
                                      infrastructure-as-code and
                                      documented deployment

  Officer resistance                  Co-design, training, case feedback
                                      and transparent performance
                                      measures

  Data-sharing restrictions           Legal basis review and
                                      source-by-source agreements

  AI hallucination / leakage          Grounded retrieval, least
                                      privilege, redaction, tool
                                      constraints and abstention

  Over-complex MVP                    Strict P0 scope and
                                      acceptance-based release gates
  -----------------------------------------------------------------------

## 21. Build instructions for an AI-assisted development environment

Create a new repository; do not modify an existing revenue system. Start
with architecture decision records, data contracts, threat model and an
executable synthetic-data fixture. Implement features in vertical slices
with migrations, typed API schemas, tests and screenshots. Keep
state-specific rules in configuration and versioned rule tables, not
hard-coded UI logic.

-   Repository layout: apps/web; apps/api; workers/ingestion;
    workers/risk; packages/contracts; infra; docs; tests;
    fixtures/synthetic.

-   First slice: login → synthetic taxpayer import → taxpayer profile →
    obligation → risk signal → analyst review → approved case →
    dashboard metric.

-   For each feature, require user story, API contract, database
    migration, permission test, audit event, integration test and
    acceptance screenshot.

-   Seed demo data with clearly fictional Nigerian names and businesses;
    never insert real taxpayer records into AI development prompts.

-   Maintain decision log for unresolved legal, privacy, data and
    deployment questions.

## 22. Definition of done and next decisions

Definition of done: all P0 acceptance tests pass; security and privacy
reviews completed; state-specific legal catalogue signed off; data
reconciled; operational runbooks and backup restore tested; trained
pilot users sign off; executive metrics have transparent definitions.

Decisions required before coding production connectors: (1) sponsoring
SIRS and technical counterpart; (2) approved tax types and reporting
periods; (3) inventory of actual revenue software and APIs; (4)
hosting/data residency and procurement approach; (5) authorised
data-sharing sources; (6) who approves legal rules, risk thresholds and
interventions; (7) available pilot staffing and budget.

## Appendix \| Initial backlog examples

  -----------------------------------------------------------------------
  Story                               Acceptance
  ----------------------------------- -----------------------------------
  As a risk analyst, I can inspect    See obligation, evidence, data
  why a taxpayer was flagged          timestamp, score contributions and
                                      uncertainty

  As a manager, I can reject an audit Decision requires reason; immutable
  referral                            event; case returns to review

  As a data steward, I can resolve a  Merge preview, dual approval,
  potential duplicate                 rollback trace

  As an executive, I can see filing   Numerator/denominator and coverage
  rates by LGA                        metadata visible

  As a legal officer, I can publish a Two-person approval; future and
  new deadline rule                   historical tests; version rollback
  -----------------------------------------------------------------------

Status: product and engineering design for validation, not a legal
opinion or confirmed representation of any state's existing datasets.
All sample scores, timings and KPIs are design assumptions requiring
pilot validation.
