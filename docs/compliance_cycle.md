# The compliance cycle

The platform is organised around a six-stage cycle. Each stage is measured from live data on the
**Compliance Cycle** page (`/cycle`, API `GET /api/v1/cycle`). Every finding and case shows the stage it is
in. The Risk Register can be filtered by stage (`/risks?stage=treat`).

| # | Stage | What happens in the platform | Measured by |
|---|---|---|---|
| 1 | **Identify risks** | Imports, connectors and webhooks bring in data; coverage is checked per tax type and period; approved rules run against a frozen snapshot | Heads monitored, sources, active rules, signals raised, fact records evaluated |
| 2 | **Assess and prioritise** | Likelihood, consequence and priority (4 × L × C, for queue order only); confidence kept separate; hard-stop holds where the data cannot support a score | Open signals by priority band; held; legal hold or dispute |
| 3 | **Analyse behaviour** | Each taxpayer is placed in one segment from the pattern of its open signals across **all** tax types; cross-tax checks (REG-102) find activity outside the net | Segment sizes and shares |
| 4 | **Decide treatment** | Officer review, then a case with the lightest treatment that will work; manager approval with segregation of duties | Confirmed signals without a case; cases awaiting approval; treatment mix |
| 5 | **Implement and engage** | Approved cases, approved templates only, contact recorded (never sent in demo), target dates | Live cases, awaiting response, overdue, actions and contacts |
| 6 | **Monitor and evaluate** | Outcomes recorded at case closure; rule precision; repeat signals after a closed case; programmes with comparison groups | Confirmed / not substantiated / corrected, precision, repeats, programmes |

Stage 6 feeds stage 1: rules with low precision are revised through the governed rule studio (new version,
backtest, legal and manager approval) before the next evaluation.

## Behaviour segments and strategies

| Segment | How it is assigned | Strategy |
|---|---|---|
| Compliant | No open signal | Make it easy: pre-filled returns, simple payment, recognition and faster service |
| Occasional slip | One isolated missed or late item | Remind and inform with an approved reminder |
| Trying but struggling | Repeated lateness or short payment, but filing and paying | Targeted assistance, education, payment arrangements |
| Outside the net | Activity (premises, commercial property or vehicles) with no direct-assessment return | Registration drive and engagement |
| Persistent non-compliance | Repeated missing returns or payments, or arrears with a missed obligation | Compliance engagement, desk review, lawful debt process |
| Unclear: data first | Only data holds or data-quality signals | Fix identity, coverage or legal verification before any contact |

Segments describe observed patterns in records. They are not judgements about intent, and they never
trigger outward action on their own.

## Where each finding sits

Stages are assigned by the finding's state, or by its live case when it has one:

| State | Stage |
|---|---|
| `review_required` | Assess |
| `approved_for_treatment` | Treat |
| Case `pending_approval` | Treat |
| Case approved, in progress or awaiting response | Implement |
| `treated` / `outcome_pending` (no live case) | Implement |
| Closed, corrected or withdrawn; case outcome recorded | Evaluate |
