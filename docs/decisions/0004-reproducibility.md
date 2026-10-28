# 0004 Snapshots and reproducibility

**Status:** accepted

## Decision
- Each evaluation freezes the complete set of fact records into a gzip JSON object, content-addressed by
  SHA-256 (`input_snapshot`). Rule versions are immutable and hashed; the run records the rule-set hash
  (rules + approved legal versions).
- Findings store the outcome and its hash, the rule version, legal version, snapshot and run.
  `reproduce` reloads the snapshot, re-evaluates the stored rule version and compares hashes.
- Findings are keyed by `rule_code | subject | period` **and** rule version. A new rule version creates a
  new finding that supersedes the old one; the old one keeps its score (and its case, if any). Rolling a
  rule back revives the earlier version's finding.
- Replaying the latest run with the same snapshot and rule set is a no-op; any other re-run upserts
  idempotently, so the same rule version + subject + period never produces two findings.
