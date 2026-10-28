# System integrations

Three ways for source systems to send data. All three end in the same pipeline as a file import:
encrypted original, signed manifest, row-level validation, quarantine of invalid identifiers or periods,
the data-sharing-basis check, supersession and rollback, and audit events. No integration can bypass them.

| Route | Who uses it | Authentication |
|---|---|---|
| **Pull connector** | NGSIRS revenue collection platform (and any system with a REST API) | API key, bearer token or OAuth2 client credentials, held in the vault |
| **Signed webhook** | Collection platform pushing settled / reversed payments as they happen | HMAC-SHA256 signature over timestamp + body |
| **JSON push API** | e-tax portal, employer payroll / ERP systems, batch jobs | OIDC token for a machine client with the `integration_client` role |

## Revenue collection platform (pull + webhook)

The demo connector `COLLECTION-PLATFORM` is configured against a simulated gateway
(`tools/mock_collection_platform`). It needs **only a new mapping** to point at the real NGSIRS
collection platform; no code changes.

**How a pull works**
1. Every `schedule_minutes` (default 15; the worker checks every 5 minutes) the connector calls the
   platform with `updated_since=<cursor>` and pages through the results.
2. Records outside the pilot's legal scope are filtered out (e.g. `revenue_code != PAYE`).
3. Multiple versions of one transaction (e.g. settled, then reversed by the bank) are de-duplicated; the
   latest version wins.
4. Source fields are mapped to the canonical `ngsirs_payment` feed, including status codes through value
   maps (`SUCCESSFUL -> settled`, `REVERSED -> reversed`, `UNALLOCATED -> unallocated`).
5. The batch is validated and committed. Invalid periods are quarantined (DAT-002); receipts that
   match no employer become PAY-005 reconciliation items, never evidence of non-payment.
6. The cursor advances only after a successful commit, so a failed run is simply retried.

**Coverage.** Incremental pulls do not claim that a period is complete. Only if NGSIRS confirms the
platform is the complete system of record for remittances, set `coverage.start` and
`coverage.settle_days` on the feed. The connector then marks periods complete once they have been
closed for that many days. Until then, missing remittances are treated as *unknown*, not missing.

**Webhook.** `POST /api/v1/connectors/COLLECTION-PLATFORM/webhook` with:

```
X-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>." + raw body)>
{"event_id": "...", "event_type": "payment.settled", "data": [<transactions>]}
```

Requests outside a 5-minute window, with a wrong signature or a reused `event_id` are refused or ignored.
The secret is read from the environment variable named in `webhook_secret_env`.

**Operations**
- Console: *Data Imports > System connectors* shows credential status (never the secret), last run,
  cursor, run history and a "Pull now" button for data stewards.
- CLI: `ngsirs connector-run COLLECTION-PLATFORM`.
- API: `GET /api/v1/connectors`, `GET /api/v1/connectors/{code}`, `POST /api/v1/connectors/{code}/run`.

### What we need from NGSIRS / the platform vendor

1. API documentation for the transactions (or receipts) endpoint: URL, authentication, paging, the
   "changed since" parameter and the response fields.
2. A sandbox URL and test credentials.
3. The revenue codes that identify PAYE, and the codes for other heads (for later workstreams).
4. Which field carries the employer's NGSIRS ID or TIN, and the period (if any).
5. Status codes for settled, pending, reversed and unallocated payments.
6. Whether webhooks are available, and the signing scheme.
7. Confirmation that the platform is the system of record for remittances (enables coverage claims).

With these, the mapping is a configuration change reviewed by a data steward, then tested against the
sandbox in shadow mode.

## JSON push API

`POST /api/v1/ingest/{feed_type}` with a bearer token for a machine client (`integration_client` role,
issued by the identity provider through the client-credentials flow) or a data steward.

```json
{
  "source": "ngsirs_treasury",
  "extracted_at": "2026-10-27T12:00:00+01:00",
  "coverage_from": null, "coverage_to": null,
  "commit": true,
  "records": [
    {"payment_reference": "PUSH-0001", "employer_id": "NGS-DEMO-EMP-0001", "tax_type": "PAYE",
     "period": "2026-09", "paid_at": "2026-10-07T10:00:00+01:00", "amount": "150000.00",
     "reversal_status": "none", "settlement_status": "settled", "allocation_status": "allocated"}
  ]
}
```

- Records use the canonical columns of the feed (`GET /api/v1/imports/templates`). Unknown fields are
  rejected (422), so mistakes surface instead of being silently dropped.
- At most 50,000 records per call. Send an `Idempotency-Key` header so retries never create duplicates.
  Re-sending identical content is also detected by content hash.
- Machine clients can only push. They cannot read findings, taxpayers or cases.

## Security notes

- Secrets live in the vault and reach the API as environment variables. The database stores only the
  variable names.
- Connectors must use HTTPS outside demo and test environments. Network egress is restricted by the
  Kubernetes `NetworkPolicy` in `infra/k8s`; add the platform's host there explicitly.
- Every pull, webhook delivery and push is an audit event with counts, cursor and batch reference.
- External (non-NGSIRS) sources stay disabled until a data-sharing basis is recorded.
