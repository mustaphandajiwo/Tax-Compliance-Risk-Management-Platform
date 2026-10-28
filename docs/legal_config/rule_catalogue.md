# Rule catalogue and code reconciliation

**Why this document exists.** PRD section 9/10 and Technical Specification section 23 both define rules
`FIL-001`..`DAT-003`, but several codes mean different things in the two documents (for example PRD
`PAY-001` is "assessed amount past due" while the Tech Spec pilot `PAY-001` is "remittance missing").
A rule code is a permanent identifier that appears in findings, cases, evidence packets and audit events,
so it must never carry two meanings.

**Decision.** The 12-rule NGSIRS pilot pack (Tech Spec section 23) keeps its codes, because it is the
NGSIRS-specific PAYE set and the fixture contract is built on it. Every PRD rule whose code would collide
is renumbered. The source of each entry is recorded in `services/risk_engine/risk_engine/catalogue.py`
(`prd_code`) and shown in Rule Configuration.

## Pilot pack (active, synthetic approvals)

| Code | Rule | Class | Default treatment | PRD origin |
|---|---|---|---|---|
| FIL-001 | PAYE accepted employer return missing for verified period | taxpayer risk | Review, then approved reminder | PRD FIL-001 |
| FIL-002 | PAYE return accepted after legally configured due date | taxpayer risk | Targeted assistance | new (repeat lateness raises likelihood) |
| FIL-003 | Repeated verified PAYE missing returns (>=3 of last 6) | taxpayer risk | Compliance engagement | new |
| PAY-001 | PAYE remittance missing on settled due period | taxpayer risk | Payment engagement | covers PRD PAY-003 |
| PAY-002 | PAYE remittance received after due date | taxpayer risk | Payment engagement | new |
| PAY-003 | Repeated PAYE remittance lateness (>=3 of last 6) | taxpayer risk | Payment engagement | PRD PAY-002 |
| PAY-004 | Remittance lower than verified declared payable | taxpayer risk | Payment engagement | PRD PAY-004 |
| PAY-005 | Unallocated or unmatched PAYE receipt | data quality | Treasury reconciliation | PRD PAY-006 |
| PAY-006 | Unresolved confirmed assessment balance | debt recovery | Reconciliation / lawful debt process | PRD PAY-001 |
| DAT-001 | Duplicate NGSIRS taxpayer identities | data quality | Identity review | PRD REG-002 |
| DAT-002 | Missing or invalid period identifier | data quality | Internal correction | new |
| DAT-003 | Source payment/return conflict | data quality | Source reconciliation | PRD DAT-003 |

## Implemented as gates rather than rules

| Code | Meaning | Where |
|---|---|---|
| DAT-004 | Unverified probabilistic / third-party match (PRD DAT-004) | Identity gate in the evaluator + match review queue |
| DAT-005 | Identifier validation failure (PRD DAT-001) | Import quarantine `invalid_identifier` |
| DAT-006 | Source extract stale (PRD DAT-002) | Evaluator hard stop `stale_source` |

## Proposed for R1 (need feeds not in the pilot)

REG-001, REG-003..REG-006, FIL-004..FIL-006, **FIL-007** (PRD FIL-002, repeated filing delays),
**FIL-008** (PRD FIL-003, interruption after sustained history), REP-001..REP-006, **PAY-007**
(PRD PAY-005, unresolved reversal; the pilot holds findings while a reversal is unconfirmed),
SYS-001..SYS-006. `REG-002` is retired (merged into DAT-001).

## Exclusions, holds and order of evaluation

Each rule lists named predicates; the evaluator applies them in a fixed order:

1. scope; 2. **exclusions** (lawful reasons the rule does not apply -> suppressed, recorded as a signal);
3. **eligibility** (false -> not applicable; *unknown* -> hold); 4. conditions;
5. **hard stops** (identity, staleness, confidence floor, rule holds) -> data hold or legal hold;
6. scoring.

| Exclusion | Effect |
|---|---|
| approved_extension | Extension moves the due date past the evaluation date |
| ceased_obligation | Obligation ended or employer ceased trading |
| processing_delay | Submission pending inside the processing window, or submitted on time |
| source_conflict | Sources disagree; DAT-003 asks for reconciliation instead |
| filing_coverage_incomplete / payment_coverage_incomplete | Absence of data is not absence of filing |
| possible_unallocated_receipt | A suspense receipt may be the payment; PAY-005 instead |
| quarantined_period_records | A quarantined row may belong to this period; DAT-002 instead |
| bank_delay_dispute | Open bank-delay dispute |
| superseded_assessment | Assessment superseded or withdrawn |

| Hold | Kind | Effect |
|---|---|---|
| identity_unverified, stale_source, obligation_unverified, low_confidence, reversal_unconfirmed, extension_undecided | data hold | Review / data-quality signal, no L/C/priority, internal treatments only |
| legal_hold (appeal, stay, officer-set) | legal hold | Score visible, outward action blocked |
| disputed | dispute | Score visible, outward action blocked |

All thresholds in the pilot rules (tolerance NGN 1,000, consequence bands, 6-period windows, 7-day
staleness, 0.98 match confidence) are **proposed pilot values** that require distributional testing in
shadow mode and NGSIRS approval (PRD section 11).
