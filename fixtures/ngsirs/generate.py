"""Generate the SYNTHETIC NGSIRS pilot fixture (Tech Spec section 23, "Executable fixture contract").

Every employer is assigned a named scenario. The expected findings for each
scenario are declared here, from the scenario's intent, *not* by running the
risk engine - otherwise the golden-file test would only prove the engine
agrees with itself. tests/integration/test_golden_fixture.py loads these files
through the real import pipeline, runs an evaluation and compares
rule_id + subject + period + status (+ hold) with expected_findings.json.

All identifiers are fake (NGS-DEMO-...), names carry "Demo", and nothing
resembles a real personal identifier. Run:  python fixtures/ngsirs/generate.py
"""

from __future__ import annotations

import calendar
import csv
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

OUT = Path(__file__).resolve().parent
WAT = timezone(timedelta(hours=1))
PERIODS = [
    f"{y}-{m:02d}"
    for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 9)]
]
AS_OF = datetime(2026, 10, 1, 0, 0, tzinfo=WAT)
EXTRACTED = datetime(2026, 9, 29, 18, 0, tzinfo=WAT)
rng = random.Random(20261028)

LGAS = [
    "AGA",
    "AGW",
    "BID",
    "BOR",
    "BOS",
    "CHA",
    "EDA",
    "GBA",
    "GUR",
    "KAT",
    "KON",
    "LAP",
    "LAV",
    "MAG",
    "MAR",
    "MAS",
    "MOK",
    "MUN",
    "PAI",
    "RAF",
    "RIJ",
    "SHI",
    "SUL",
    "TAF",
    "WUS",
]
PLACES = [
    "Tunga",
    "Kpakungu",
    "Maitumbi",
    "Bosso Estate",
    "Chanchaga",
    "Shango",
    "Barkin Sale",
    "Dutsen Kura",
    "Sauka Kahuta",
    "Limawa",
    "Jikpan",
    "Gidan Kwano",
    "Maikunkele",
    "Dama",
    "Fadikpe",
    "Tudun Fulani",
    "Kure",
    "Nasarawa",
    "Garatu",
    "Bahago",
    "Gbaiko",
    "Kodo",
    "Paiko",
    "Beji",
    "Kuta",
    "Zungeru",
    "Lambata",
    "Lemu",
    "Sabon Gari",
    "Mokwa Road",
]
TRADES = [
    "Bakery",
    "Hardware",
    "Pharmacy",
    "Logistics",
    "Microfinance",
    "Clinic",
    "Agro Processing",
    "Schools",
    "Hotels",
    "Printing",
    "Motors",
    "Foods",
    "Water",
    "Construction",
    "Textiles",
    "Poultry",
    "Rice Mills",
    "Solar",
    "Furniture",
    "Transport",
    "Engineering",
    "Supermarket",
    "Fisheries",
    "Ceramics",
]
SECTORS = [
    "retail",
    "manufacturing",
    "services",
    "agriculture",
    "construction",
    "finance",
    "education",
    "health",
]

# Synthetic legal parameters - MUST match the seeded SYNTHETIC legal versions (seed.py) but are restated here
# so the expected results are derived independently of the application code.
RETURN_DUE_DAY = {"old": 10, "new": 15}
REMIT_DUE_DAY = {"old": 10, "new": 10}
ASSESSMENT_DAYS = 30


def due(period: str, kind: str) -> datetime:
    y, m = int(period[:4]), int(period[5:7])
    regime = "old" if y < 2026 else "new"
    day = (RETURN_DUE_DAY if kind == "return" else REMIT_DUE_DAY)[regime]
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    day = min(day, calendar.monthrange(ny, nm)[1])
    return datetime(ny, nm, day, 23, 59, 59, tzinfo=WAT)


def iso(d: datetime | date | None) -> str:
    return d.isoformat() if d else ""


@dataclass
class Expect:
    rule: str
    subject: str
    period: str | None
    hold: str | None = None


@dataclass
class Emp:
    n: int
    scenario: str
    lga: str
    name: str
    sector: str
    segment: str
    base_amount: int
    linked: bool = True
    obligation: dict[str, str] | None = field(default_factory=dict)
    ref: str = ""
    tp_ref: str = ""
    tin: str = ""

    def __post_init__(self) -> None:
        self.ref = f"NGS-DEMO-EMP-{self.n:04d}"
        self.tp_ref = f"NGS-DEMO-TP-{self.n:04d}"
        self.tin = f"NGS-DEMO-TIN-{self.n:06d}"


SCENARIOS = [
    ("clean", 60),
    ("late_filing_once", 6),
    ("late_filing_repeated", 4),
    ("missing_one", 6),
    ("missing_three", 4),
    ("extension_granted", 3),
    ("extension_pending", 2),
    ("processing_delay", 3),
    ("late_ingest", 2),
    ("late_payment_once", 5),
    ("late_payment_repeated", 4),
    ("underpayment", 4),
    ("partial_with_credit", 2),
    ("within_tolerance", 2),
    ("reversed", 3),
    ("reversed_repaid", 2),
    ("reversal_pending", 2),
    ("suspense_receipt", 3),
    ("unmatched_reference", 2),
    ("invalid_period", 2),
    ("filing_source_conflict", 2),
    ("payment_source_conflict", 2),
    ("unverified_identity", 2),
    ("ceased", 3),
    ("no_obligation", 2),
    ("obligation_pending_verification", 2),
    ("assessment_unpaid", 3),
    ("assessment_appealed", 2),
    ("assessment_superseded", 1),
    ("assessment_paid", 1),
    ("rejected_uncorrected", 2),
    ("legal_transition", 2),
]


def norm(name: str) -> str:
    stop = {"ltd", "limited", "plc", "nig", "nigeria", "enterprises", "and", "the", "co", "company"}
    return " ".join(sorted(t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in stop))


def build_employers() -> list[Emp]:
    names: set[str] = set()
    out: list[Emp] = []
    n = 0
    for scenario, count in SCENARIOS:
        for _ in range(count):
            n += 1
            lga = rng.choice(["CHA", "BOS"]) if rng.random() < 0.4 else rng.choice(LGAS)
            while True:
                name = f"{rng.choice(PLACES)} {rng.choice(TRADES)} Demo Ltd"
                if name not in names:
                    break
            names.add(name)
            out.append(
                Emp(
                    n,
                    scenario,
                    lga,
                    name,
                    rng.choice(SECTORS),
                    rng.choice(["large", "medium", "small"]),
                    rng.randrange(80, 2400) * 1000,
                )
            )
    # Hygiene: no accidental near-duplicate names in the same LGA (would create unplanned DAT-001 pairs).
    for i, a in enumerate(out):
        for b in out[i + 1 :]:
            if a.lga == b.lga and SequenceMatcher(None, norm(a.name), norm(b.name)).ratio() >= 0.85:
                b.name = b.name.replace(" Demo Ltd", f" {b.n} Demo Ltd")
    return out


def main() -> None:
    employers = build_employers()
    taxpayers, emp_rows, obligations, extensions = [], [], [], []
    returns, returns_late, returns_legacy, payments, payments_bank, assessments = [], [], [], [], [], []
    expected: list[Expect] = []
    scenario_rows = []

    def declared(e: Emp, p: str) -> int:
        return e.base_amount + (int(p[5:7]) * 1000)

    def file_ok(
        e: Emp,
        p: str,
        rows: list | None = None,
        accepted_at: datetime | None = None,
        status: str = "accepted",
        submitted_at: datetime | None = None,
        employees: bool = True,
    ) -> None:
        d = due(p, "return")
        acc = accepted_at if accepted_at is not None else d - timedelta(days=3, hours=13, minutes=59)
        (rows if rows is not None else returns).append(
            {
                "filing_reference": f"NGS-DEMO-RET-{e.n:04d}-{p}",
                "employer_id": e.ref,
                "period": p,
                "status": status,
                "submitted_at": iso(submitted_at or (acc - timedelta(hours=2))),
                "accepted_at": iso(acc) if status in ("accepted", "corrected") else "",
                "amount_declared": f"{declared(e, p)}.00",
                "employee_count": str(10 + e.n % 40) if employees and e.n % 3 else "",
            }
        )

    def pay_ok(
        e: Emp,
        p: str,
        amount: int | None = None,
        paid_at: datetime | None = None,
        rows: list | None = None,
        ref_suffix: str = "",
        **extra: str,
    ) -> None:
        d = due(p, "remit")
        row = {
            "payment_reference": f"NGS-DEMO-PAY-{e.n:04d}-{p}{ref_suffix}",
            "employer_id": e.ref,
            "tax_type": "PAYE",
            "period": p,
            "paid_at": iso(paid_at or (d - timedelta(days=2, hours=12, minutes=59))),
            "amount": f"{amount if amount is not None else declared(e, p)}.00",
            "reversal_status": "none",
            "settlement_status": "settled",
            "allocation_status": "allocated",
            "bank_delay_dispute": "false",
            "credit_adjustment": "0.00",
        }
        row.update(extra)
        (rows if rows is not None else payments).append(row)

    for e in employers:
        s = e.scenario
        scenario_rows.append({"employer_id": e.ref, "scenario": s, "lga": e.lga})
        tp_name = e.name
        linked_ref = e.tp_ref
        if s == "unverified_identity":
            tp_name = e.name.replace("Demo Ltd", "Holdings Demo Ltd").replace(" ", " Trading ", 1)
            linked_ref = ""
        taxpayers.append(
            {
                "source_taxpayer_id": e.tp_ref,
                "taxpayer_type": "company",
                "status": "active",
                "taxpayer_name": tp_name,
                "tin": e.tin,
                "jurisdiction": "NG-NI",
                "lga_code": e.lga,
                "sector": e.sector,
                "effective_from": "2019-01-01",
                "effective_to": "",
            }
        )
        ceased = s == "ceased"
        emp_rows.append(
            {
                "source_employer_id": e.ref,
                "linked_taxpayer_id": linked_ref,
                "employer_name": e.name,
                "activity_from": "2019-01-01",
                "activity_to": "2026-03-31" if ceased else "",
                "office_id": f"OFF-{e.lga}",
                "lga_code": e.lga,
                "sector": e.sector,
                "segment": e.segment,
                "status": "ceased" if ceased else "active",
            }
        )
        if s != "no_obligation":
            obligations.append(
                {
                    "taxpayer_id": e.ref,
                    "tax_type": "PAYE",
                    "obligation_type": "paye_employer",
                    "legal_code": "PAYE_EMPLOYER_MONTHLY_RETURN",
                    "statutory_version": "",
                    "effective_from": "2020-01-01",
                    "effective_to": "2026-03-31" if ceased else "",
                    "status": "pending_verification" if s == "obligation_pending_verification" else "active",
                    "exemption_status": "none",
                }
            )

        for p in PERIODS:
            skip_file = skip_pay = False
            if s == "no_obligation":
                skip_file = skip_pay = True
            elif ceased and p > "2026-03":
                skip_file = skip_pay = True
            elif s == "missing_one" and p == "2026-06":
                skip_file = skip_pay = True
                expected += [Expect("FIL-001", e.ref, p), Expect("PAY-001", e.ref, p)]
            elif s == "missing_three" and p in ("2026-04", "2026-06", "2026-08"):
                skip_file = skip_pay = True
                expected += [Expect("FIL-001", e.ref, p), Expect("PAY-001", e.ref, p)]
            elif s == "unverified_identity" and p == "2026-06":
                skip_file = skip_pay = True
                expected += [
                    Expect("FIL-001", e.ref, p, "data_hold"),
                    Expect("PAY-001", e.ref, p, "data_hold"),
                ]
            elif s == "obligation_pending_verification" and p == "2026-08":
                skip_file = skip_pay = True
                expected += [
                    Expect("FIL-001", e.ref, p, "data_hold"),
                    Expect("PAY-001", e.ref, p, "data_hold"),
                ]

            # ---- filing
            if not skip_file:
                d = due(p, "return")
                if s == "late_filing_once" and p == "2026-03":
                    file_ok(e, p, accepted_at=d + timedelta(days=4, hours=-13))
                    expected.append(Expect("FIL-002", e.ref, p))
                elif s == "late_filing_repeated" and p in ("2026-03", "2026-04", "2026-06", "2026-08"):
                    file_ok(e, p, accepted_at=d + timedelta(days=6, hours=-13))
                    expected.append(Expect("FIL-002", e.ref, p))
                elif s == "extension_granted" and p == "2026-05":
                    extensions.append(
                        {
                            "employer_id": e.ref,
                            "obligation_type": "paye_return",
                            "period": p,
                            "new_due_date": (d + timedelta(days=10)).date().isoformat(),
                            "status": "approved",
                            "approved_by": "demo.extension.officer",
                        }
                    )
                    file_ok(e, p, accepted_at=d + timedelta(days=5, hours=-13))
                elif s == "extension_pending" and p == "2026-07":
                    extensions.append(
                        {
                            "employer_id": e.ref,
                            "obligation_type": "paye_return",
                            "period": p,
                            "new_due_date": (d + timedelta(days=20)).date().isoformat(),
                            "status": "pending",
                            "approved_by": "",
                        }
                    )
                    expected.append(Expect("FIL-001", e.ref, p, "data_hold"))
                elif s == "processing_delay" and p == "2026-08":
                    file_ok(e, p, status="submitted", submitted_at=d - timedelta(days=2))
                elif s == "late_ingest" and p == "2026-08":
                    file_ok(e, p, rows=returns_late)
                elif s == "rejected_uncorrected" and p == "2026-07":
                    file_ok(e, p, status="rejected", submitted_at=d - timedelta(days=3))
                    expected.append(Expect("FIL-001", e.ref, p))
                elif s == "legal_transition" and p == "2025-12":
                    # Old regime due 2026-01-10; accepted 2026-01-12 is late (would be on time under the 2026 rule).
                    file_ok(e, p, accepted_at=datetime(2026, 1, 12, 10, 0, tzinfo=WAT))
                    expected.append(Expect("FIL-002", e.ref, p))
                elif s == "legal_transition" and p == "2026-01":
                    # New regime due 2026-02-15; accepted 2026-02-12 is on time (late under the old rule).
                    file_ok(e, p, accepted_at=datetime(2026, 2, 12, 10, 0, tzinfo=WAT))
                elif s == "filing_source_conflict" and p == "2026-02":
                    file_ok(e, p)
                    returns_legacy.append(
                        {
                            "filing_reference": f"NGS-DEMO-LEG-{e.n:04d}-{p}",
                            "employer_id": e.ref,
                            "period": p,
                            "status": "not_received",
                            "submitted_at": "",
                            "accepted_at": "",
                            "amount_declared": "",
                            "employee_count": "",
                        }
                    )
                    expected.append(Expect("DAT-003", e.ref, p))
                else:
                    file_ok(e, p)

            # ---- payment
            if not skip_pay:
                d = due(p, "remit")
                dec = declared(e, p)
                if s == "late_payment_once" and p == "2026-02":
                    pay_ok(e, p, paid_at=d + timedelta(days=3))
                    expected.append(Expect("PAY-002", e.ref, p))
                elif s == "late_payment_repeated" and p in ("2026-03", "2026-04", "2026-06", "2026-08"):
                    pay_ok(e, p, paid_at=d + timedelta(days=5))
                    expected.append(Expect("PAY-002", e.ref, p))
                elif s == "underpayment" and p == "2026-05":
                    pay_ok(e, p, amount=int(dec * 0.6))
                    expected.append(Expect("PAY-004", e.ref, p))
                elif s == "partial_with_credit" and p == "2026-05":
                    pay_ok(e, p, amount=dec - 5000, credit_adjustment="5000.00")
                elif s == "within_tolerance" and p == "2026-05":
                    pay_ok(e, p, amount=dec - 500)
                elif s == "reversed" and p == "2026-04":
                    pay_ok(e, p, reversal_status="reversed")
                    expected.append(Expect("PAY-001", e.ref, p))
                elif s == "reversed_repaid" and p == "2026-04":
                    pay_ok(e, p, reversal_status="reversed")
                    pay_ok(e, p, ref_suffix="-R", paid_at=d - timedelta(days=1))
                elif s == "reversal_pending" and p == "2026-04":
                    pay_ok(e, p, reversal_status="reversal_pending")
                elif s == "suspense_receipt" and p == "2026-07":
                    pay_ok(e, p, allocation_status="suspense")
                    expected.append(Expect("PAY-005", f"NGS-DEMO-PAY-{e.n:04d}-{p}", None))
                elif s == "unmatched_reference" and p == "2026-07":
                    payments.append(
                        {
                            "payment_reference": f"NGS-DEMO-PAY-X{e.n:03d}-{p}",
                            "employer_id": f"NGS-DEMO-EMP-9{e.n:03d}",
                            "tax_type": "PAYE",
                            "period": p,
                            "paid_at": iso(d - timedelta(days=2)),
                            "amount": f"{dec}.00",
                            "reversal_status": "none",
                            "settlement_status": "settled",
                            "allocation_status": "",
                            "bank_delay_dispute": "false",
                            "credit_adjustment": "0.00",
                        }
                    )
                    expected += [
                        Expect("PAY-005", f"NGS-DEMO-PAY-X{e.n:03d}-{p}", None),
                        Expect("PAY-001", e.ref, p),
                    ]
                elif s == "invalid_period" and p == "2026-03":
                    pay_ok(e, p)
                    payments[-1]["period"] = "2026-13"
                    expected.append(Expect("DAT-002", f"ngsirs_payment:NGS-DEMO-PAY-{e.n:04d}-{p}", None))
                elif s == "payment_source_conflict" and p == "2026-05":
                    pay_ok(e, p)
                    pay_ok(e, p, amount=dec + 10000, rows=payments_bank)
                    expected.append(Expect("DAT-003", e.ref, p))
                else:
                    pay_ok(e, p)

        if s.startswith("assessment_"):
            appeal = "appealed" if s == "assessment_appealed" else "none"
            status = "superseded" if s == "assessment_superseded" else "served"
            outstanding = 0 if s == "assessment_paid" else 350000 + e.n * 1000
            aref = f"NGS-DEMO-ASM-{e.n:04d}"
            assessments.append(
                {
                    "assessment_id": aref,
                    "employer_id": e.ref,
                    "period": "2026-02",
                    "assessment_type": "additional",
                    "amount": f"{outstanding or 200000}.00",
                    "served_on": "2026-05-01",
                    "due_date": "",
                    "appeal_status": appeal,
                    "outstanding_amount": f"{outstanding}.00",
                    "status": status,
                }
            )
            if s == "assessment_unpaid":
                expected.append(Expect("PAY-006", aref, "2026-02"))
            elif s == "assessment_appealed":
                expected.append(Expect("PAY-006", aref, "2026-02", "legal_hold"))

        # Repeat-pattern rules fire once, at the anchor (latest due) period.
        if s == "missing_three":
            expected.append(Expect("FIL-003", e.ref, "2026-08"))
        if s == "late_payment_repeated":
            expected.append(Expect("PAY-003", e.ref, "2026-08"))

    # Duplicate identities: two shared-TIN pairs and one near-identical-name pair (DAT-001).
    clean = [e for e in employers if e.scenario == "clean"]
    for i, e in enumerate(clean[:2], start=1):
        dup_ref = f"NGS-DEMO-TP-D{i:03d}"
        other_lga = LGAS[(LGAS.index(e.lga) + 7) % len(LGAS)]
        taxpayers.append(
            {
                "source_taxpayer_id": dup_ref,
                "taxpayer_type": "company",
                "status": "active",
                "taxpayer_name": f"Registry Duplicate {i} Demo Ventures",
                "tin": e.tin,
                "jurisdiction": "NG-NI",
                "lga_code": other_lga,
                "sector": e.sector,
                "effective_from": "2021-06-01",
                "effective_to": "",
            }
        )
        expected.append(Expect("DAT-001", "~".join(sorted([e.tp_ref, dup_ref])), None))
    e = clean[2]
    taxpayers.append(
        {
            "source_taxpayer_id": "NGS-DEMO-TP-D003",
            "taxpayer_type": "company",
            "status": "active",
            "taxpayer_name": e.name.replace("Demo Ltd", "Demo Limited"),
            "tin": "NGS-DEMO-TIN-900003",
            "jurisdiction": "NG-NI",
            "lga_code": e.lga,
            "sector": e.sector,
            "effective_from": "2022-03-01",
            "effective_to": "",
        }
    )
    expected.append(Expect("DAT-001", "~".join(sorted([e.tp_ref, "NGS-DEMO-TP-D003"])), None))
    # One taxpayer row with an invalid TIN is quarantined at import (identifier validation gate).
    taxpayers.append(
        {
            "source_taxpayer_id": "NGS-DEMO-TP-Q001",
            "taxpayer_type": "company",
            "status": "active",
            "taxpayer_name": "Quarantine Example Demo Ltd",
            "tin": "12345",
            "jurisdiction": "NG-NI",
            "lga_code": "CHA",
            "sector": "retail",
            "effective_from": "2023-01-01",
            "effective_to": "",
        }
    )

    def write(name: str, rows: list[dict]) -> None:
        if not rows:
            return
        with (OUT / name).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write("taxpayers.csv", taxpayers)
    write("employers.csv", emp_rows)
    write("obligations.csv", obligations)
    write("extensions.csv", extensions)
    write("paye_returns.csv", returns)
    write("paye_returns_late.csv", returns_late)
    write("paye_returns_legacy.csv", returns_legacy)
    write("payments.csv", payments)
    write("payments_bank.csv", payments_bank)
    write("assessments.csv", assessments)
    write("scenarios.csv", scenario_rows)

    cov = {"coverage_from": PERIODS[0], "coverage_to": PERIODS[-1]}
    manifest = {
        "as_of": AS_OF.isoformat(),
        "period_from": PERIODS[0],
        "period_to": PERIODS[-1],
        "note": "SYNTHETIC NGSIRS pilot fixture. Load in order; evaluate as at as_of.",
        "loads": [
            {
                "file": "taxpayers.csv",
                "feed_type": "ngsirs_taxpayer",
                "source": "ngsirs_registration",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "employers.csv",
                "feed_type": "ngsirs_employer",
                "source": "ngsirs_registration",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "obligations.csv",
                "feed_type": "ngsirs_obligation",
                "source": "ngsirs_registration",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "extensions.csv",
                "feed_type": "ngsirs_extension",
                "source": "ngsirs_registration",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "paye_returns.csv",
                "feed_type": "ngsirs_paye_return",
                "source": "ngsirs_etax_portal",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
            {
                "file": "paye_returns_late.csv",
                "feed_type": "ngsirs_paye_return",
                "source": "ngsirs_etax_portal",
                "extracted_at": (EXTRACTED + timedelta(hours=20)).isoformat(),
            },
            {
                "file": "paye_returns_legacy.csv",
                "feed_type": "ngsirs_paye_return",
                "source": "ngsirs_legacy_register",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "payments.csv",
                "feed_type": "ngsirs_payment",
                "source": "ngsirs_treasury",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
            {
                "file": "payments_bank.csv",
                "feed_type": "ngsirs_payment",
                "source": "ngsirs_bank_feed",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "assessments.csv",
                "feed_type": "ngsirs_assessment",
                "source": "ngsirs_assessment_ledger",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    findings = sorted(
        (
            {
                "rule_id": x.rule,
                "subject": x.subject,
                "period": x.period,
                "status": "review_required",
                "hold": x.hold,
            }
            for x in expected
        ),
        key=lambda r: (r["rule_id"], r["subject"], r["period"] or ""),
    )
    (OUT / "expected_findings.json").write_text(
        json.dumps(
            {
                "as_of": AS_OF.isoformat(),
                "periods": [PERIODS[0], PERIODS[-1]],
                "employers": len(employers),
                "scenarios": dict(SCENARIOS),
                "count": len(findings),
                "compare": ["rule_id", "subject", "period", "status", "hold"],
                "findings": findings,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"{len(employers)} employers, {len(returns)} returns, {len(payments)} payments, "
        f"{len(findings)} expected findings"
    )


if __name__ == "__main__":
    main()
