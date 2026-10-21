# Data contracts (PRD §13)

Every connector is read-only and must have an owner, a legal basis, a refresh cadence, a data
dictionary, a schema version, reconciliation totals, error handling and a revocation mechanism. The
table below lists the MVP datasets. The real source systems will be confirmed in Discovery (sprint 0);
until then, the names below are placeholders used by the synthetic fixture.

| Dataset | Placeholder source | Owner (TBC) | Legal basis (TBC) | Cadence | Schema |
|---|---|---|---|---|---|
| `taxpayers` | `NG-SIRS-REGISTER`, `NG-SIRS-LEGACY` | SIRS registration unit | SIRS statutory mandate | daily | 1.0 |
| `taxpayers` (unregistered) | `NG-BUSINESS-PERMITS` | State business-permit agency | Data-sharing agreement required | monthly | 1.0 |
| `employments` | `NG-PAYE-PORTAL` | PAYE unit | SIRS statutory mandate | monthly | 1.0 |
| `returns` | `NG-PAYE-PORTAL` | PAYE / DA units | SIRS statutory mandate | daily | 1.0 |
| `payments` | `NG-COLLECTIONS` | Collections / treasury | SIRS statutory mandate | daily | 1.0 |

## Submission envelope — `POST /v1/imports`

```json
{
  "dataset": "returns",
  "source_system": "NG-PAYE-PORTAL",
  "schema_version": "1.0",
  "idempotency_key": "paye-portal-2026-10-18-001",
  "checksum": "<sha256 of canonical JSON of records>",
  "extracted_at": "2026-10-18",
  "records": [ ... ]
}
```

- **Checksum:** `sha256(json.dumps(records, sort_keys=True, separators=(",", ":"), default=str))`.
  A mismatch returns `422`.
- **Idempotency:** resubmitting the same key with the same checksum returns the original batch. The
  same key with a different checksum returns `409`.
- **`extracted_at`:** the date the source system extracted the data. Feed freshness and the data
  confidence of every downstream score depend on it, so connectors must set it accurately.
- **Outcome per record:** `accepted | rejected | duplicate | quarantined`. A batch is `reconciled`
  when `total = accepted + rejected + duplicate + quarantined`.

## Record schemas (v1.0)

Every record carries a `source_record_id` that is stable and unique within its source. Duplicates
are detected on `(source_system, source_record_id)`.

### taxpayers
| Field | Type | Req | Notes |
|---|---|---|---|
| taxpayer_type | `individual` \| `business` | ✓ | Never assume a business and its owner are the same taxpayer |
| name | string(2–250) | ✓ | |
| tin / nin / cac_rc | string | – | Stored only as tenant-salted HMAC + masked hint |
| registration_status | `registered` \| `unregistered` \| `deregistered` | – | default `registered` |
| tax_residence | state code | ✓ | Jurisdiction safeguard |
| lga, sector | string | – | Dashboard dimensions |
| is_employer, self_employed | bool | – | Drive PAYE / DA eligibility |
| operating_status | `active` \| `dormant` \| `closed` | – | `closed_on` stops obligations after closure |
| registered_on, closed_on | date | – | |

### employments
`employer_tin`, `employee_tin`, `start_date` (required), `end_date`, `monthly_gross`.
A record is quarantined if either TIN is unknown.

### returns
`tin`, `tax_type` (`PAYE`\|`DA`), `period` (`YYYY-MM` for PAYE, `YYYY` for DA), `filing_date`,
`reported_income ≥ 0`, `reported_amount ≥ 0` (declared liability), `employee_count`. A record is
quarantined if its TIN is unknown. The latest filed return for a period is taken as the declared
liability.

### payments
`tin`, `tax_type`, `period` (optional), `amount > 0`, `payment_date` (not in the future),
`allocation_status` (`allocated`\|`unallocated`\|`disputed`). A payment with no period is always
`unallocated`. Unallocated or disputed amounts lower confidence in a shortfall signal and change its
recommended action to `correct_data`.

## Error handling
- Rejected and quarantined records keep their raw payload and a list of errors
  (`GET /v1/imports/{id}/records?status=…`).
- After master data is corrected, a data steward can reprocess a quarantined record
  (`POST /v1/import-records/{id}/reprocess`). The batch counts are updated and the action is audited.

## Revocation
To revoke a connector: disable its service credential and stop scheduling its batches. Data already
ingested stays, with its provenance (`source_system`, `source_batch_id`), so it can be purged under
the retention policy once that has been agreed (decision log D-07).
