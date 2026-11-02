# Revenue heads: every tax the authority administers

PAYE has its own detailed pipeline (employer returns, remittance, extensions, assessments). Every other tax,
levy or charge is a **revenue head** configured in the jurisdiction pack. Each head follows one obligation
**pattern**. Patterns are code and are reviewed like code; heads are configuration.

| Pattern | Obligation codes (legal parameters) | When something is due |
|---|---|---|
| `monthly_return_payment` | `H_MONTHLY_RETURN`, `H_MONTHLY_PAYMENT` (`due_day_of_following_month`) | A day of the following month |
| `annual_return_payment` | `H_ANNUAL_RETURN`, `H_ANNUAL_PAYMENT` (`due_month`, `due_day`) | A date in the year after the tax year |
| `annual_demand` | `H_DEMAND` (`payment_days_after_service`) | Days after the demand notice is **served** |
| `licence_renewal` | `H_RENEWAL` (`grace_days`) | Days after the recorded expiry date |
| `transaction` | `H_TRANSACTION` (`days_after_transaction`) | Days after a recorded disposal or instrument |
| `annual_levy` | `H_ANNUAL_LEVY` (`due_month`, `due_day`) | A date within the levy year |

## Heads in the shipped packs (state level)

| Code | Head | Pattern | Subject |
|---|---|---|---|
| `PAYE` | Pay As You Earn (built in) | monthly | employer |
| `PITDA` | Personal income tax by direct assessment | annual return and payment | individual |
| `WHT` | Withholding tax on income of individuals | monthly return and payment | paying agent |
| `CGT` | Capital gains tax (individuals) | transaction | individual |
| `SD` | Stamp duties (instruments executed by individuals) | transaction | individual |
| `LUC` | Land use charge | annual demand | property |
| `BPR` | Business premises registration and renewal | licence renewal | premises |
| `MVL` | Motor vehicle licence and road taxes | licence renewal | vehicle |
| `DEVL` | Development levy (individuals) | annual levy | individual |
| `GAM` | Pools betting, lotteries, gaming and casino taxes | monthly return and payment | operator |
| `MKT` | Market taxes and levies (state-financed markets) | annual demand | premises |

Company income tax, VAT and other national taxes are excluded: a national agency administers them. Each
head's legal parameters are **synthetic placeholders**. The authority's legal officers confirm them from the
authenticated texts and approve them (maker-checker) before any rule uses them. Another state levy (signage,
naming of streets, right of occupancy, a local rate) is added by adding a head with an existing pattern.

### Property: land use charge, not tenement rates

`property_regime` in the pack is `land_use_charge` (one property head with the `annual_demand` pattern) or
`none`. `tenement_rate` is **reserved**: a pack that sets it is rejected with a message saying the legacy
property-rate model is a later customisation. States that still run the older property tax get that module
when they onboard.

## Data

| Feed | What it carries |
|---|---|
| `revenue_account` | One row per account under a head: individual, agent, operator, property, premises or vehicle, linked to the taxpayer register; use class, category, assessed value |
| `revenue_liability` | Returns filed, demands issued or served, licence expiries, registry transactions, levies; period is `YYYY-MM` or `YYYY` |
| `revenue_payment` | Collections per head (treasury or the collection platform) |

Coverage is recorded **per head and period** (`revenue_liability:LUC` for 2025), so a land use charge
extract says nothing about motor vehicle licences. A file covering January to December also covers that
tax year.

## Safeguards specific to heads

- **A demand creates a payment obligation only once served.** An unserved demand is `DAT-102`, and a missing
  annual bill is `DAT-101`. Both are authority-side billing gaps and never a taxpayer default.
- **An undeclared transaction** is `FIL-102`, not a payment signal, because there is no declared amount yet.
- **An unknown owner** (a property or vehicle with no verified taxpayer) makes the signal a data hold with
  no score, and the treatment is identity review.
- **An appeal on a demand** keeps the score visible but blocks outward action.

## Rules (bundled pack `revenue_heads_v1.json`)

Ten rules apply to every head (scope `tax_type: "*"`), and each explanation names the head:

| Rule | Signal |
|---|---|
| FIL-101 | Return missing |
| FIL-102 | Recorded transaction without a declaration |
| FIL-103 | Return filed late |
| PAY-101 | Liability unpaid after due date |
| PAY-102 | Payment short of liability |
| PAY-103 | Paid late |
| REG-101 | Licence or registration not renewed |
| REG-102 | Cross-tax: business premises, commercial property or commercial vehicles held by an individual with no direct-assessment return |
| DAT-101 | Demand or levy bill not issued |
| DAT-102 | Demand issued but not served |

An authority can draft a rule for a single head (scope `tax_type: "LUC"`) through the governed rule studio.
