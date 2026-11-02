"""Generate the SYNTHETIC pilot fixture for a jurisdiction pack (reference spec "executable fixture contract").

Every employer is assigned a named scenario. The expected findings for each
scenario are declared here, from the scenario's intent, *not* by running the
risk engine - otherwise the golden-file test would only prove the engine
agrees with itself. tests/integration/test_golden_fixture.py loads these files
through the real import pipeline, runs an evaluation and compares
rule_id + subject + period + status (+ hold) with expected_findings.json.

All identifiers are fake (DEMO-...), names carry "Demo", and nothing
resembles a real personal identifier. Areas, places, time zone and users come from
jurisdictions/<pack>/pack.json. Run:  python fixtures/generate.py --pack demo   (writes fixtures/demo/)
"""

from __future__ import annotations

import calendar
import csv
import json
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PACK_NAME = sys.argv[sys.argv.index("--pack") + 1] if "--pack" in sys.argv else "demo"
PACK = json.loads((ROOT.parent / "jurisdictions" / PACK_NAME / "pack.json").read_text())
OUT = ROOT / PACK_NAME
TZ = ZoneInfo(PACK["timezone"])  # the authority's time zone; deadlines fall at its end of day
AREAS = [a["code"] for a in PACK["areas"]]
PILOT_AREAS = [a["code"] for a in PACK["areas"] if a["pilot"]] or AREAS[:2]
PLACES = PACK["fixture"]["places"]
JURISDICTION = PACK["jurisdiction"]
PERIODS = [
    f"{y}-{m:02d}"
    for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 9)]
]
AS_OF = datetime(2026, 10, 1, 0, 0, tzinfo=TZ)
EXTRACTED = datetime(2026, 9, 29, 18, 0, tzinfo=TZ)
rng = random.Random(20261028)

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
    return datetime(ny, nm, day, 23, 59, 59, tzinfo=TZ)


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
    area: str
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
        self.ref = f"DEMO-EMP-{self.n:04d}"
        self.tp_ref = f"DEMO-TP-{self.n:04d}"
        self.tin = f"DEMO-TIN-{self.n:06d}"


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
            area = rng.choice(PILOT_AREAS) if rng.random() < 0.4 else rng.choice(AREAS)
            while True:
                name = f"{rng.choice(PLACES)} {rng.choice(TRADES)} Demo Ltd"
                if name not in names:
                    break
            names.add(name)
            out.append(
                Emp(
                    n,
                    scenario,
                    area,
                    name,
                    rng.choice(SECTORS),
                    rng.choice(["large", "medium", "small"]),
                    rng.randrange(80, 2400) * 1000,
                )
            )
    # Hygiene: no accidental near-duplicate names in the same LGA (would create unplanned DAT-001 pairs).
    for i, a in enumerate(out):
        for b in out[i + 1 :]:
            if a.area == b.area and SequenceMatcher(None, norm(a.name), norm(b.name)).ratio() >= 0.85:
                b.name = b.name.replace(" Demo Ltd", f" {b.n} Demo Ltd")
    return out


# ---------------------------------------------------------------------------------------------------------
# Revenue heads beyond PAYE. Each scenario declares its expected finding here, independently of the engine.
# ---------------------------------------------------------------------------------------------------------
HEADS = {h["code"]: h for h in PACK.get("tax_heads", [])}


def param(code: str, period: str, name: str) -> int:
    start = date(int(period[:4]), int(period[5:7]) if len(period) > 4 else 1, 1)
    for v in PACK["legal_versions"]:
        lo = date.fromisoformat(v["effective_from"])
        hi = date.fromisoformat(v["effective_to"]) if v["effective_to"] else date(2100, 1, 1)
        if v["code"] == code and lo <= start <= hi:
            return int(v["parameters"][name])
    raise KeyError(code)


def eod(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)


def monthly_due(code: str, p: str) -> datetime:
    y, m = int(p[:4]), int(p[5:7])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    day = min(param(code, p, "due_day_of_following_month"), calendar.monthrange(ny, nm)[1])
    return eod(date(ny, nm, day))


def at(d: date, hour: int = 11) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=TZ)


def revenue_head_fixture(employers: list[Emp], taxpayers: list[dict], expected: list[Expect]) -> list[dict]:
    """Accounts, liabilities and payments for every configured head; returns manifest load entries."""
    if not HEADS:
        return []
    accounts: list[dict] = []
    liabilities: dict[str, list[dict]] = {h: [] for h in HEADS}
    payments: dict[str, list[dict]] = {h: [] for h in HEADS}
    seq = {"l": 0, "p": 0}
    years = ["2025", "2026"]

    def person(n: int, status: str = "active", area: str | None = None) -> str:
        ref = f"DEMO-TP-I{n:03d}"
        taxpayers.append(
            {
                "source_taxpayer_id": ref,
                "taxpayer_type": "individual",
                "status": status,
                "taxpayer_name": f"{PLACES[n % len(PLACES)]} Demo Person {n}",
                "tin": f"DEMO-TIN-{700000 + n:06d}",
                "jurisdiction": JURISDICTION,
                "area_code": area or PILOT_AREAS[n % len(PILOT_AREAS)],
                "sector": "",
                "effective_from": "2018-01-01",
                "effective_to": "",
            }
        )
        return ref

    def company(code: str, name: str, n: int) -> str:
        ref = f"DEMO-TP-{code}"
        taxpayers.append(
            {
                "source_taxpayer_id": ref,
                "taxpayer_type": "company",
                "status": "active",
                "taxpayer_name": name,
                "tin": f"DEMO-TIN-{800000 + n:06d}",
                "jurisdiction": JURISDICTION,
                "area_code": PILOT_AREAS[0],
                "sector": "gaming",
                "effective_from": "2019-01-01",
                "effective_to": "",
            }
        )
        return ref

    def account(acct: str, head: str, subject: str, name: str, tp: str | None, **kw: str) -> str:
        accounts.append(
            {
                "account_id": acct,
                "tax_head": head,
                "subject_type": subject,
                "taxpayer_id": tp or "",
                "employer_id": kw.get("employer", ""),
                "account_name": name,
                "area_code": kw.get("area", PILOT_AREAS[0]),
                "use_class": kw.get("use", ""),
                "category": kw.get("category", ""),
                "assessed_value": kw.get("value", ""),
                "status": kw.get("status", "active"),
                "effective_from": kw.get("since", "2020-01-01"),
                "effective_to": kw.get("until", ""),
            }
        )
        return acct

    def liability(head: str, acct: str, period: str, kind: str, status: str, **kw: object) -> None:
        seq["l"] += 1
        liabilities[head].append(
            {
                "liability_reference": f"DEMO-LIA-{head}-{seq['l']:04d}",
                "account_id": acct,
                "tax_head": head,
                "period": period,
                "kind": kind,
                "status": status,
                "event_date": iso(kw.get("event")),  # type: ignore[arg-type]
                "filed_at": iso(kw.get("filed")),  # type: ignore[arg-type]
                "amount": f"{kw['amount']}.00" if kw.get("amount") is not None else "",
                "appeal_status": str(kw.get("appeal", "none")),
            }
        )

    def pay(head: str, acct: str, period: str, amount: int, when: datetime) -> None:
        seq["p"] += 1
        payments[head].append(
            {
                "payment_reference": f"DEMO-RPAY-{head}-{seq['p']:04d}",
                "account_id": acct,
                "tax_head": head,
                "period": period,
                "paid_at": iso(when),
                "amount": f"{amount}.00",
                "reversal_status": "none",
                "settlement_status": "settled",
                "allocation_status": "allocated",
            }
        )

    # --- Personal income tax, direct assessment (annual return and payment) -----------------------------
    if "PITDA" in HEADS:
        due25 = eod(
            date(
                2026,
                param("PITDA_ANNUAL_RETURN", "2025", "due_month"),
                param("PITDA_ANNUAL_RETURN", "2025", "due_day"),
            )
        )
        cases = [
            (1, "on_time", 180000),
            (2, "not_filed", None),
            (3, "late_filed_late_paid", 220000),
            (4, "filed_unpaid", 400000),
            (5, "part_paid", 300000),
            (6, "ceased", None),
            (7, "unknown_owner", None),
        ]
        for n, case, amount in cases:
            tp = person(n) if case != "unknown_owner" else None
            acct = account(
                f"DEMO-DA-{n:03d}",
                "PITDA",
                "individual",
                f"Direct assessment - Demo Person {n}",
                tp or f"DEMO-TP-I9{n:02d}",
                status="ceased" if case == "ceased" else "active",
                until="2024-12-31" if case == "ceased" else "",
                since="2019-01-01",
            )
            if case == "on_time":
                liability(
                    "PITDA",
                    acct,
                    "2025",
                    "return",
                    "accepted",
                    filed=due25 - timedelta(days=12),
                    amount=amount,
                )
                pay("PITDA", acct, "2025", amount, due25 - timedelta(days=12))
            elif case == "not_filed":
                expected.append(Expect("FIL-101", acct, "2025"))
            elif case == "late_filed_late_paid":
                liability(
                    "PITDA",
                    acct,
                    "2025",
                    "return",
                    "accepted",
                    filed=due25 + timedelta(days=40),
                    amount=amount,
                )
                pay("PITDA", acct, "2025", amount, due25 + timedelta(days=40))
                expected += [Expect("FIL-103", acct, "2025"), Expect("PAY-103", acct, "2025")]
            elif case == "filed_unpaid":
                liability(
                    "PITDA",
                    acct,
                    "2025",
                    "return",
                    "accepted",
                    filed=due25 - timedelta(days=5),
                    amount=amount,
                )
                expected.append(Expect("PAY-101", acct, "2025"))
            elif case == "part_paid":
                liability(
                    "PITDA",
                    acct,
                    "2025",
                    "return",
                    "accepted",
                    filed=due25 - timedelta(days=5),
                    amount=amount,
                )
                pay("PITDA", acct, "2025", 100000, due25 - timedelta(days=5))
                expected.append(Expect("PAY-102", acct, "2025"))
            elif case == "unknown_owner":
                expected.append(Expect("FIL-101", acct, "2025", "data_hold"))

    # --- Withholding tax (monthly agent return and remittance) ------------------------------------------
    if "WHT" in HEADS:
        agents = [e for e in employers if e.scenario == "clean"][10:14]
        for i, e in enumerate(agents, start=1):
            acct = account(
                f"DEMO-WHT-{i:03d}",
                "WHT",
                "agent",
                f"WHT agent - {e.name}",
                e.tp_ref,
                employer=e.ref,
                area=e.area,
            )
            for p in PERIODS:
                d = monthly_due("WHT_MONTHLY_RETURN", p)
                amount = 40000 + 1000 * i
                if i == 2 and p in ("2026-06", "2026-07"):
                    continue  # agent stopped filing
                liability("WHT", acct, p, "return", "accepted", filed=d - timedelta(days=4), amount=amount)
                if i == 3 and p == "2026-05":
                    continue  # filed but not remitted
                when = d + timedelta(days=3) if (i == 4 and p == "2026-03") else d - timedelta(days=4)
                pay("WHT", acct, p, amount, when)
            if i == 2:
                expected += [Expect("FIL-101", acct, "2026-06"), Expect("FIL-101", acct, "2026-07")]
            if i == 3:
                expected.append(Expect("PAY-101", acct, "2026-05"))
            if i == 4:
                expected.append(Expect("PAY-103", acct, "2026-03"))

    # --- Gaming taxes (monthly operator return and payment) ---------------------------------------------
    if "GAM" in HEADS:
        for i in (1, 2):
            tp = company(f"O{i:03d}", f"Lucky {PLACES[i]} Pools Demo Ltd", i)
            acct = account(
                f"DEMO-GAM-{i:03d}", "GAM", "operator", f"Gaming operator - Lucky {PLACES[i]} Pools", tp
            )
            for p in PERIODS:
                d = monthly_due("GAM_MONTHLY_RETURN", p)
                amount = 150000 + 5000 * i
                liability("GAM", acct, p, "return", "accepted", filed=d - timedelta(days=2), amount=amount)
                paid = amount * 6 // 10 if (i == 2 and p == "2026-04") else amount
                pay("GAM", acct, p, paid, d - timedelta(days=2))
        expected.append(Expect("PAY-102", "DEMO-GAM-002", "2026-04"))

    # --- Capital gains tax and stamp duties (transaction-based) -----------------------------------------
    for head, rows in (
        (
            "CGT",
            [
                (10, date(2026, 2, 14), "declared_paid"),
                (11, date(2026, 4, 3), "undeclared"),
                (12, date(2026, 8, 25), "declared_unpaid"),
            ],
        ),
        ("SD", [(13, date(2026, 1, 10), "undeclared"), (14, date(2026, 5, 6), "declared_paid")]),
    ):
        if head not in HEADS:
            continue
        code = f"{head}_TRANSACTION"
        for n, tx, case in rows:
            tp = person(n)
            acct = account(f"DEMO-{head}-I{n:03d}", head, "individual", f"{head} - Demo Person {n}", tp)
            p = f"{tx.year}-{tx.month:02d}"
            liability(head, acct, p, "transaction", "recorded", event=tx, amount=2500000 + n * 10000)
            d = eod(tx + timedelta(days=param(code, p, "days_after_transaction")))
            if case == "undeclared":
                expected.append(Expect("FIL-102", acct, p))
                continue
            amount = 120000 + n * 1000
            liability(head, acct, p, "return", "filed", filed=d - timedelta(days=10), amount=amount)
            if case == "declared_paid":
                pay(head, acct, p, amount, d - timedelta(days=10))
            else:
                expected.append(Expect("PAY-101", acct, p))

    # --- Development levy (annual flat levy) ------------------------------------------------------------
    if "DEVL" in HEADS:
        for n, case in ((1, "paid"), (2, "unpaid_2026"), (3, "new_2026")):
            tp = f"DEMO-TP-I{n:03d}"
            acct = account(
                f"DEMO-DEVL-I{n:03d}",
                "DEVL",
                "individual",
                f"Development levy - Demo Person {n}",
                tp,
                since="2026-01-01" if case == "new_2026" else "2018-01-01",
            )
            for y in years:
                if case == "new_2026" and y == "2025":
                    continue
                due = eod(
                    date(
                        int(y),
                        param("DEVL_ANNUAL_LEVY", y, "due_month"),
                        param("DEVL_ANNUAL_LEVY", y, "due_day"),
                    )
                )
                liability("DEVL", acct, y, "levy", "issued", event=date(int(y), 1, 5), amount=1000)
                if case == "unpaid_2026" and y == "2026":
                    expected.append(Expect("PAY-101", acct, "2026"))
                    continue
                pay("DEVL", acct, y, 1000, due - timedelta(days=30))

    # --- Land use charge (annual demand on property) ----------------------------------------------------
    if "LUC" in HEADS:
        props = [
            (1, "company", "commercial", "paid", "paid"),
            (2, "individual", "residential", "unpaid", "paid"),
            (3, "individual", "commercial", "paid", "part_paid"),
            (4, "company", "commercial", "not_issued", "paid"),
            (5, "individual", "residential", "not_served", "paid"),
            (6, "unknown", "residential", "unpaid", "paid"),
            (7, "company", "commercial", "appealed", "paid"),
            (8, "individual", "commercial", "paid", "paid"),
            (9, "individual", "residential", "paid", "paid"),
        ]
        owners = {8: 20, 9: 22, 2: 15, 3: 16, 5: 17}
        for n, owner, use, c25, c26 in props:
            if owner == "individual":
                tp = person(owners[n])
            elif owner == "company":
                tp = [e for e in employers if e.scenario == "clean"][20 + n].tp_ref
            else:
                tp = None
            value = 20_000_000 + n * 5_000_000
            acct = account(
                f"DEMO-LUC-P{n:03d}",
                "LUC",
                "property",
                f"Property {n}, {PLACES[n]} (SYNTHETIC)",
                tp,
                use=use,
                value=str(value),
            )
            amount = 60000 + n * 15000
            for y, case in (("2025", c25), ("2026", c26)):
                served_on = date(int(y), 2, 15)
                due = eod(served_on + timedelta(days=param("LUC_DEMAND", y, "payment_days_after_service")))
                if case == "not_issued":
                    expected.append(Expect("DAT-101", acct, y))
                    continue
                if case == "not_served":
                    liability("LUC", acct, y, "demand", "issued", amount=amount)
                    expected.append(Expect("DAT-102", acct, y))
                    continue
                liability(
                    "LUC",
                    acct,
                    y,
                    "demand",
                    "served",
                    event=served_on,
                    amount=amount,
                    appeal="appealed" if case == "appealed" else "none",
                )
                if case == "paid":
                    pay("LUC", acct, y, amount, due - timedelta(days=10))
                elif case == "part_paid":
                    pay("LUC", acct, y, amount // 3, due - timedelta(days=10))
                    expected.append(Expect("PAY-102", acct, y))
                elif case == "unpaid":
                    expected.append(Expect("PAY-101", acct, y, "data_hold" if owner == "unknown" else None))
                elif case == "appealed":
                    expected.append(Expect("PAY-101", acct, y, "legal_hold"))

    # --- Market levies (annual demand on stalls) --------------------------------------------------------
    if "MKT" in HEADS:
        for i, c26 in ((1, "unpaid"), (2, "paid")):
            tp = [e for e in employers if e.scenario == "clean"][30 + i].tp_ref
            acct = account(
                f"DEMO-MKT-{i:03d}",
                "MKT",
                "premises",
                f"Market stall {i}, Central Market (SYNTHETIC)",
                tp,
                use="commercial",
            )
            for y in years:
                served_on = date(int(y), 1, 20)
                due = eod(served_on + timedelta(days=param("MKT_DEMAND", y, "payment_days_after_service")))
                liability("MKT", acct, y, "demand", "served", event=served_on, amount=24000)
                if y == "2026" and c26 == "unpaid":
                    expected.append(Expect("PAY-101", acct, y))
                    continue
                pay("MKT", acct, y, 24000, due - timedelta(days=5))

    # --- Business premises and motor vehicle licences (renewal on expiry) -------------------------------
    if "BPR" in HEADS:
        for n, owner, case in (
            (1, 23, "renewed"),
            (2, 20, "not_renewed"),
            (3, 24, "renewed_late"),
            (4, 25, "ceased"),
        ):
            tp = person(owner) if owner != 20 else "DEMO-TP-I020"
            acct = account(
                f"DEMO-BPR-B{n:03d}",
                "BPR",
                "premises",
                f"Business premises {n}, {PLACES[n + 3]} (SYNTHETIC)",
                tp,
                use="commercial",
                status="ceased" if case == "ceased" else "active",
                until="2025-06-30" if case == "ceased" else "",
            )
            if case == "ceased":
                continue
            expiry = date(2025, 12, 31)
            due = eod(expiry + timedelta(days=param("BPR_RENEWAL", "2025", "grace_days")))
            liability("BPR", acct, "2025", "renewal_due", "issued", event=expiry, amount=25000)
            if case == "renewed":
                pay("BPR", acct, "2025", 25000, due - timedelta(days=15))
            elif case == "renewed_late":
                pay("BPR", acct, "2025", 25000, due + timedelta(days=33))
                expected.append(Expect("PAY-103", acct, "2025"))
            else:
                expected.append(Expect("REG-101", acct, "2025"))
    if "MVL" in HEADS:
        for n, owner, use, case in (
            (1, 1, "commercial", "renewed"),
            (2, 21, "commercial", "not_renewed"),
            (3, None, "private", "not_renewed"),
        ):
            tp = None if owner is None else (person(owner) if owner == 21 else f"DEMO-TP-I{owner:03d}")
            acct = account(
                f"DEMO-MVL-V{n:03d}",
                "MVL",
                "vehicle",
                f"Vehicle DEMO-{n:03d}-XX ({use})",
                tp,
                use=use,
                category="bus" if use == "commercial" else "car",
            )
            expiry = date(2026, 4 + n, 28)
            due = eod(expiry + timedelta(days=param("MVL_RENEWAL", "2026", "grace_days")))
            liability("MVL", acct, "2026", "renewal_due", "issued", event=expiry, amount=18000)
            if case == "renewed":
                pay("MVL", acct, "2026", 18000, due - timedelta(days=20))
            else:
                expected.append(Expect("REG-101", acct, "2026", "data_hold" if tp is None else None))

    # --- Cross-tax: business, property or vehicle activity without a direct-assessment return ----------
    if "PITDA" in HEADS:
        # Person 20: business premises (not renewed) and a commercial property; person 21: a commercial bus.
        expected += [Expect("REG-102", "DEMO-TP-I020", "2025"), Expect("REG-102", "DEMO-TP-I021", "2025")]
        # Person 23 renewed business premises, person 24 renewed late, person 16 owns a commercial property:
        # none has a direct-assessment return either.
        expected += [
            Expect("REG-102", "DEMO-TP-I016", "2025"),
            Expect("REG-102", "DEMO-TP-I023", "2025"),
            Expect("REG-102", "DEMO-TP-I024", "2025"),
        ]

    def write(name: str, rows: list[dict]) -> None:
        with (OUT / name).open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    loads: list[dict] = []
    write("revenue_accounts.csv", accounts)
    loads.append(
        {
            "file": "revenue_accounts.csv",
            "feed_type": "revenue_account",
            "source": "revenue_registers",
            "extracted_at": EXTRACTED.isoformat(),
        }
    )
    for head in HEADS:
        pattern = HEADS[head]["pattern"]
        monthly = pattern in ("monthly_return_payment", "transaction")
        cov = (
            {"coverage_from": PERIODS[0], "coverage_to": PERIODS[-1]}
            if monthly
            else {"coverage_from": "2025-01", "coverage_to": "2026-12"}
        )
        source = (
            "land_registry"
            if pattern == "transaction"
            else "etax_portal"
            if "return" in pattern
            else "billing_system"
        )
        if liabilities[head]:
            write(f"head_{head.lower()}_liabilities.csv", liabilities[head])
            loads.append(
                {
                    "file": f"head_{head.lower()}_liabilities.csv",
                    "feed_type": "revenue_liability",
                    "source": source,
                    "extracted_at": EXTRACTED.isoformat(),
                    **cov,
                }
            )
            if pattern == "transaction":  # declarations come through the e-tax portal
                decl = [r for r in liabilities[head] if r["kind"] == "return"]
                trans = [r for r in liabilities[head] if r["kind"] != "return"]
                write(f"head_{head.lower()}_liabilities.csv", trans)
                if decl:
                    write(f"head_{head.lower()}_declarations.csv", decl)
                    loads.append(
                        {
                            "file": f"head_{head.lower()}_declarations.csv",
                            "feed_type": "revenue_liability",
                            "source": "etax_portal",
                            "extracted_at": EXTRACTED.isoformat(),
                        }
                    )
        if payments[head]:
            write(f"head_{head.lower()}_payments.csv", payments[head])
            loads.append(
                {
                    "file": f"head_{head.lower()}_payments.csv",
                    "feed_type": "revenue_payment",
                    "source": "treasury",
                    "extracted_at": EXTRACTED.isoformat(),
                    **cov,
                }
            )
    return loads


def main() -> None:
    OUT.mkdir(exist_ok=True)
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
                "filing_reference": f"DEMO-RET-{e.n:04d}-{p}",
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
            "payment_reference": f"DEMO-PAY-{e.n:04d}-{p}{ref_suffix}",
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
        scenario_rows.append({"employer_id": e.ref, "scenario": s, "area": e.area})
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
                "jurisdiction": JURISDICTION,
                "area_code": e.area,
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
                "office_id": f"OFF-{e.area}",
                "area_code": e.area,
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
                    file_ok(e, p, accepted_at=datetime(2026, 1, 12, 10, 0, tzinfo=TZ))
                    expected.append(Expect("FIL-002", e.ref, p))
                elif s == "legal_transition" and p == "2026-01":
                    # New regime due 2026-02-15; accepted 2026-02-12 is on time (late under the old rule).
                    file_ok(e, p, accepted_at=datetime(2026, 2, 12, 10, 0, tzinfo=TZ))
                elif s == "filing_source_conflict" and p == "2026-02":
                    file_ok(e, p)
                    returns_legacy.append(
                        {
                            "filing_reference": f"DEMO-LEG-{e.n:04d}-{p}",
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
                    expected.append(Expect("PAY-005", f"DEMO-PAY-{e.n:04d}-{p}", None))
                elif s == "unmatched_reference" and p == "2026-07":
                    payments.append(
                        {
                            "payment_reference": f"DEMO-PAY-X{e.n:03d}-{p}",
                            "employer_id": f"DEMO-EMP-9{e.n:03d}",
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
                        Expect("PAY-005", f"DEMO-PAY-X{e.n:03d}-{p}", None),
                        Expect("PAY-001", e.ref, p),
                    ]
                elif s == "invalid_period" and p == "2026-03":
                    pay_ok(e, p)
                    payments[-1]["period"] = "2026-13"
                    expected.append(Expect("DAT-002", f"payment:DEMO-PAY-{e.n:04d}-{p}", None))
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
            aref = f"DEMO-ASM-{e.n:04d}"
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
        dup_ref = f"DEMO-TP-D{i:03d}"
        other_area = AREAS[(AREAS.index(e.area) + 7) % len(AREAS)]
        taxpayers.append(
            {
                "source_taxpayer_id": dup_ref,
                "taxpayer_type": "company",
                "status": "active",
                "taxpayer_name": f"Registry Duplicate {i} Demo Ventures",
                "tin": e.tin,
                "jurisdiction": JURISDICTION,
                "area_code": other_area,
                "sector": e.sector,
                "effective_from": "2021-06-01",
                "effective_to": "",
            }
        )
        expected.append(Expect("DAT-001", "~".join(sorted([e.tp_ref, dup_ref])), None))
    e = clean[2]
    taxpayers.append(
        {
            "source_taxpayer_id": "DEMO-TP-D003",
            "taxpayer_type": "company",
            "status": "active",
            "taxpayer_name": e.name.replace("Demo Ltd", "Demo Limited"),
            "tin": "DEMO-TIN-900003",
            "jurisdiction": JURISDICTION,
            "area_code": e.area,
            "sector": e.sector,
            "effective_from": "2022-03-01",
            "effective_to": "",
        }
    )
    expected.append(Expect("DAT-001", "~".join(sorted([e.tp_ref, "DEMO-TP-D003"])), None))
    # One taxpayer row with an invalid TIN is quarantined at import (identifier validation gate).
    taxpayers.append(
        {
            "source_taxpayer_id": "DEMO-TP-Q001",
            "taxpayer_type": "company",
            "status": "active",
            "taxpayer_name": "Quarantine Example Demo Ltd",
            "tin": "12345",
            "jurisdiction": JURISDICTION,
            "area_code": PILOT_AREAS[0],
            "sector": "retail",
            "effective_from": "2023-01-01",
            "effective_to": "",
        }
    )

    head_loads = revenue_head_fixture(employers, taxpayers, expected)

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
    write("users.csv", PACK["fixture"]["users"])

    cov = {"coverage_from": PERIODS[0], "coverage_to": PERIODS[-1]}
    manifest = {
        "as_of": AS_OF.isoformat(),
        "period_from": PERIODS[0],
        "period_to": PERIODS[-1],
        "note": f"SYNTHETIC pilot fixture for {PACK['name']}. Load in order; evaluate as at as_of.",
        "loads": [
            {
                "file": "taxpayers.csv",
                "feed_type": "taxpayer",
                "source": "registration_system",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "employers.csv",
                "feed_type": "employer",
                "source": "registration_system",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "obligations.csv",
                "feed_type": "obligation",
                "source": "registration_system",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "extensions.csv",
                "feed_type": "extension",
                "source": "registration_system",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "paye_returns.csv",
                "feed_type": "paye_return",
                "source": "etax_portal",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
            {
                "file": "paye_returns_late.csv",
                "feed_type": "paye_return",
                "source": "etax_portal",
                "extracted_at": (EXTRACTED + timedelta(hours=20)).isoformat(),
            },
            {
                "file": "paye_returns_legacy.csv",
                "feed_type": "paye_return",
                "source": "legacy_register",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "payments.csv",
                "feed_type": "payment",
                "source": "treasury",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
            {
                "file": "payments_bank.csv",
                "feed_type": "payment",
                "source": "bank_feed",
                "extracted_at": EXTRACTED.isoformat(),
            },
            {
                "file": "assessments.csv",
                "feed_type": "assessment",
                "source": "assessment_ledger",
                "extracted_at": EXTRACTED.isoformat(),
                **cov,
            },
            *head_loads,
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
