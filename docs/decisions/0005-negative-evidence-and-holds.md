# 0005 Negative evidence, hard stops and holds

**Status:** accepted

## Decision
- **Coverage tables** record, per feed and period (optionally per LGA), whether a complete extract was
  received. A missing return or remittance only counts when coverage is complete; otherwise the rule is
  suppressed (`*_coverage_incomplete`).
- **Event time over ingestion time.** Acceptance and payment timestamps decide lateness; late ingestion of
  an on-time filing changes nothing.
- **System of record.** Only system-of-record sources clear or establish filing/payment; secondary sources
  (legacy register, bank feed) are used to detect conflicts (DAT-003).
- **Tri-state eligibility.** An obligation with no approved legal version, or a due date that cannot be
  established, is *unknown* and becomes a hold, never a pass or a fail.
- **Data holds** (identity, staleness, obligation unverified, low confidence, unconfirmed reversal,
  undecided extension) remove the score entirely and restrict treatments to internal ones.
- **Legal holds and disputes** keep the score visible (for prioritising review) but block outward action.
- Officer-set legal holds are stored as a marker on the finding and fed back into the next snapshot.
