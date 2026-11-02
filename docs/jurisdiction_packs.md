# Jurisdiction packs: onboarding a revenue authority

A jurisdiction pack holds every fact that differs between revenue authorities. The engine, rules DSL,
importer, workflows, security model and UI are shared; the pack is configuration. Packs live at
`jurisdictions/<name>/pack.json` and are validated on load by `apps/api/taxrisk_api/jurisdiction.py`.
An invalid pack fails to load, with the reason: an unknown time zone, a bad regex, an unknown feed type, a
legal version citing a missing instrument, a missing obligation parameter, or duplicate area codes.

| Pack | Authority | Notes |
|---|---|---|
| `demo` | Demo State Revenue Service (`fictional: true`) | Default. Neutral naming ("District"), used for presentations |
| `ng-niger` | Niger State Internal Revenue Service | Example real-jurisdiction pack: 25 LGAs; state and federal instruments listed as placeholders |

## What a pack contains

| Field | Purpose |
|---|---|
| `code`, `name`, `short_name`, `description` | Tenant code (also the OIDC `tenant` claim) and the branding shown in the console |
| `fictional` | `true` shows a "fictional authority" notice on the sign-in page |
| `country`, `jurisdiction` | Recorded on every legal version and evidence packet |
| `timezone` | IANA zone. Deadlines run to 23:59:59 local time, and analytics windows and import timestamps use it |
| `currency`, `locale` | ISO 4217 code and BCP 47 locale for money and date formatting in the API and UI |
| `area_label`, `area_label_plural` | What the administrative areas are called ("District", "LGA", "County", "Municipality") |
| `areas[]` | `code` (2–8 upper-case characters), `name`, `pilot`, `verified`. One tax office is created per area |
| `tin_pattern` | Regex for the taxpayer identifier format, used in validation |
| `settings` | Operating mode, confidence floor, processing window, identity-match threshold |
| `approved_templates` | The only message texts a contact can use. All must stay SYNTHETIC until the authority approves them |
| `data_sources[]` | Source name, feed types, owner, system-of-record flag, external flag, freshness SLA, data-sharing basis |
| `instruments[]` | Legal instruments (code, title, authority, jurisdiction, status, note) |
| `legal_versions[]` | Effective-dated obligation parameters per instrument, for example `due_day_of_following_month` |
| `tax_scope[]` | Workstreams in or out of scope (`pilot_primary`, `secondary_next`, `next`, `future`, `excluded`) |
| `retention[]` | Retention period and legal basis per data class |
| `fixture` | Place names for synthetic employers and the demo users (roles, unit, area scope, purposes) |

Obligation codes, their required parameters and the feed types are defined in code
(`services/legal.py` `OBLIGATION_CODES`, `services/importer` `FEEDS`). A new obligation *type* is a code
change. A new authority, instrument, deadline or area is not.

## Steps to add an authority

1. **Copy a pack.** `cp -r jurisdictions/demo jurisdictions/<name>`. Edit `pack.json`: set `fictional`
   to `false` for a real authority, then fill in the areas, time zone, currency and sources.
2. **Legal library.** List the instruments. Every legal version stays a *SYNTHETIC placeholder* until the
   authority's legal officers confirm it from authenticated texts, then approve it in the console
   (*Admin → Legal*, maker-checker). Do not take rates or deadlines from the internet.
3. **Generate a synthetic fixture.** `uv run python fixtures/generate.py --pack <name>` writes
   `fixtures/<name>/` with users, employers, returns, payments and the independently declared
   `expected_findings.json`.
4. **Run it.** `TAXRISK_DEFAULT_PACK=<name> uv run taxrisk demo` migrates, seeds the tenant from the pack,
   loads the fixture through the real import pipeline, evaluates and checks the golden file.
   `uv run taxrisk packs` lists the available packs.
5. **Test it.** The parametrised unit test `tests/unit/test_importer_and_legal.py` validates every pack
   under `jurisdictions/`. Add the generate command to CI's *Fixture is reproducible* step.
6. **Identity provider.** Set the `tenant` claim to the pack `code` in the authority's OIDC realm (see
   `infra/keycloak/taxrisk-realm.json`) and map its groups to platform roles.
7. **Real data.** Configure connectors and mappings (`docs/integrations.md`), record a data-sharing basis
   for each external source, and run in shadow mode before any operational use (`docs/operations.md`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TAXRISK_DEFAULT_PACK` | `demo` | Pack seeded by `taxrisk seed` and `taxrisk demo`, and the default tenant |
| `TAXRISK_DEFAULT_TENANT_CODE` | the pack's `code` | Override the tenant code used when a token carries none |
| `TAXRISK_JURISDICTIONS_PATH` | `<repo>/jurisdictions` | Load packs from another directory, such as a private repo holding an authority's real pack |

Production installations are single-tenant: one authority per deployment. Several packs can be seeded into
one database for demonstrations, and row-level security keeps them apart.

## Rules that do not change between authorities

- The platform produces risk indicators for human review, never automated assessments or sanctions.
- A taxpayer's statutory rights (filing, objection, appeal, access to their own records) are never a
  premium feature, and internal risk scores are never shown to taxpayers or sold.
- Unknown is not non-compliant: incomplete coverage, unverified obligations and uncertain identity become
  holds, not scores.
