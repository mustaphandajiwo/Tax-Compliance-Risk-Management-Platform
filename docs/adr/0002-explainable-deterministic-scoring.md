# ADR-0002: Deterministic, reproducible scoring over frozen inputs

- Status: Accepted · Date: 2026-10-21

## Context
FR-05 requires the score for a past run to be reproducible. PRD §6 requires that every score stores
the model, ruleset and obligation versions, the inputs and their hashes, the applied weights, the
signals, the reason codes and the confidence. PRD §16 says the same frozen inputs and version must
give identical results.

## Decision
- `build_inputs()` freezes everything an evaluation reads into canonical JSON, stored on
  `risk_assessments.inputs` with `inputs_hash`.
- `evaluate(inputs, weights, thresholds)` is a pure function: no clock, no DB, no randomness. The
  `as_of` date is part of the inputs. Its output is hashed (`output_hash`).
- `POST /v1/risk-assessments/{id}/reproduce` re-runs `evaluate` on the stored inputs with the recorded
  model version and compares hashes. The acceptance suite checks every assessment produced from the
  full pilot fixture.
- Signal logic changes bump `ENGINE_VERSION`. Weight or threshold changes create a new `RiskModel`
  version that needs approval from someone other than its author.
- Scoring follows PRD §6: each applicable dimension gets a 0–100 score (the highest signal severity,
  plus 5 for each further signal), non-applicable dimensions are excluded and the weights
  renormalised. Data confidence is the mean of coverage, timeliness, matching certainty and evidence
  reliability. If any one component is below 0.25, confidence is capped at 0.5.
- Adverse prioritisation is suppressed when confidence is below the model minimum, or when there is
  an unresolved merge candidate with confidence ≥ 0.9. The alert then goes to `data_verification`,
  and only `correct_data` or `no_action` can be proposed.

## Consequences
- Every score can be audited and explained without the live data that produced it.
- Inputs are stored per assessment, which costs space. A retention policy decides how long superseded
  snapshots are kept (see the decision log).
