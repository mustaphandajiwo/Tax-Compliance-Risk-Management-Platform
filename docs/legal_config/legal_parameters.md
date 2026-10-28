# Legal configuration (SYNTHETIC placeholders)

**Nothing in this file or in the seeded legal library is a statement of Niger State or federal law.**
PRD section 19: the Niger State Tax Administration and Consolidation Law 2023 (as amended), applicable
Niger State schedules and revenue instruments, the Nigeria Tax Act 2025, the Nigeria Tax Administration Act
2025 and the June 2026 transition guidance must be reviewed by NGSIRS legal officers before any rule is
activated. No rate or deadline may be taken from an internet FAQ.

## How legal configuration works

- **Instruments** (`legal_instrument`) record the authority, jurisdiction and status of each source text.
- **Legal rule versions** (`legal_rule_version`) carry an obligation code, an effective window and
  parameters (e.g. `due_day_of_following_month`). They are drafted, then approved by a *different* person
  with the legal approver role. Approved versions are immutable at the database level.
- **Resolution.** For a tax period, the version in force is the approved version with the latest
  `effective_from` that covers the period start. A later version therefore supersedes an open-ended
  earlier one from its own effective date without editing it. Periods before 1 January 2026 resolve to
  the prior-law version.
- **No approved version -> obligation unverified.** The engine turns any signal for that period into a
  data hold; nothing is scored.
- **Period schedules** (`period_schedule`) materialise due dates from the resolved version for each
  evaluated period and record which legal version produced them; findings cite that version.

## Seeded synthetic versions

| Obligation code | Version | Instrument | Effective | Parameters (SYNTHETIC) |
|---|---|---|---|---|
| PAYE_EMPLOYER_MONTHLY_RETURN | 2020.1-SYN | PRIOR-PAYE-LAW | 2020-01-01 .. 2025-12-31 | due day 10 of following month |
| PAYE_EMPLOYER_MONTHLY_RETURN | 2026.1-SYN | NTAA-2025 | from 2026-01-01 | due day 15 of following month |
| PAYE_EMPLOYER_REMITTANCE | 2020.1-SYN | PRIOR-PAYE-LAW | 2020-01-01 .. 2025-12-31 | due day 10 |
| PAYE_EMPLOYER_REMITTANCE | 2026.1-SYN | NTAA-2025 | from 2026-01-01 | due day 10 |
| PAYE_ASSESSMENT | 2020.1-SYN / 2026.1-SYN | as above | as above | payment 30 days after service |

The return deadline deliberately differs between the two synthetic regimes so the fixture can prove
period-specific resolution (scenario `legal_transition`).

## Replacing the placeholders (go-live checklist)

1. Legal officer records the authenticated instrument(s) and amendment history.
2. A drafter enters each obligation version with the provision reference and effective dates; a second
   legal approver approves it (`POST /api/v1/legal/versions`, `/approve`).
3. The data steward confirms the obligation register feed reflects only legal-team-approved obligations.
4. Rule versions that bind to the obligation are re-approved (the legal approval step checks an approved
   legal version exists).
5. A shadow evaluation is reviewed before any case workflow is opened (PRD section 16, Gate B/C).

## Open decisions for NGSIRS (PRD section 17)

- System of record for taxpayer IDs, returns, payments and assessments (seeded sources are placeholders).
- Legally correct PAYE employer return schedules and historical transitions.
- Operational definition of "active employer" and approved exceptions.
- Evidence-confidence floor (seeded 0.9) and review thresholds after shadow-mode profiling.
- Named lawful approvers for rules, data access, outbound contact and audit selection.
- Hosting / data residency and information security standards.
