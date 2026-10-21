#!/usr/bin/env python3
"""Deterministic synthetic dataset for the Niger State pilot (PRD §19, §21).

ALL DATA IS FICTIONAL. Names are random combinations of common Nigerian given names and surnames;
businesses are invented; every identifier carries the ``SYN`` prefix. Never replace this with real
taxpayer records, and never paste real records into AI development tools.

Behaviour profiles are planted so each risk signal and safeguard is exercised:
compliant, late filer, non-filer, under-payer, income drop, seasonal (safeguard), closed
(no obligation), dormant (low confidence), misallocated payments (data correction), unregistered
entities, duplicates across source systems, and invalid rows for reconciliation.

Usage: python fixtures/synthetic/generate.py [--out fixtures/synthetic/niger-pilot] [--seed 2026]
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

STATE = "NI"
LGAS = [
    "Agaie", "Agwara", "Bida", "Borgu", "Bosso", "Chanchaga", "Edati", "Gbako", "Gurara", "Katcha", "Kontagora",
    "Lapai", "Lavun", "Magama", "Mariga", "Mashegu", "Mokwa", "Munya", "Paikoro", "Rafi", "Rijau", "Shiroro",
    "Suleja", "Tafa", "Wushishi",
]
SECTORS = ["Agriculture", "Retail", "Education", "Construction", "Hospitality", "Transport", "Health", "ICT",
           "Manufacturing", "Professional services"]
GIVEN = ["Aisha", "Abubakar", "Hauwa", "Musa", "Zainab", "Ibrahim", "Fatima", "Usman", "Maryam", "Yakubu", "Ndagi",
         "Nma", "Kolo", "Jiya", "Chinedu", "Ngozi", "Tunde", "Bisi", "Emeka", "Halima", "Sani", "Amina", "Danjuma",
         "Rakiya", "Gana", "Salihu", "Ladi", "Baba", "Esther", "Daniel"]
FAMILY = ["Bello", "Mohammed", "Ndayako", "Gbate", "Kolo", "Etsu", "Abdullahi", "Yisa", "Tsado", "Shaba", "Okafor",
          "Adeyemi", "Nwosu", "Danladi", "Mamman", "Garba", "Jibrin", "Saidu", "Nuhu", "Alhassan", "Baba", "Sheshi"]
BIZ_A = ["Kpada", "Gurara", "Kainji", "Zuma", "Jebba", "Shiroro", "Tagwai", "Gbako", "Edu", "Lapai", "Nupe", "Minna",
         "Bosso", "Kaduna Road", "Paiko", "Sabon Gari", "Tunga", "Maitumbi", "Chanchaga", "Kutigi"]
BIZ_B = ["Agro Ventures", "Fresh Farms", "Building Works", "Logistics", "Pharmacy", "Schools", "Hotels", "Tech Hub",
         "Foods", "Mills", "Motors", "Consulting", "Clinics", "Rice Processing", "Supermarket", "Printing Press"]
SECTOR_OF = {"Agro Ventures": "Agriculture", "Fresh Farms": "Agriculture", "Building Works": "Construction",
             "Logistics": "Transport", "Pharmacy": "Health", "Schools": "Education", "Hotels": "Hospitality",
             "Tech Hub": "ICT", "Foods": "Manufacturing", "Mills": "Manufacturing", "Motors": "Transport",
             "Consulting": "Professional services", "Clinics": "Health", "Rice Processing": "Agriculture",
             "Supermarket": "Retail", "Printing Press": "Professional services"}

PAYE_MONTHS = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13) if (y, m) <= (2026, 9)]
EXTRACTED_AT = "2026-10-18"
CUTOFF = date.fromisoformat(EXTRACTED_AT)
PAYE_RATE = 0.07  # illustrative effective PAYE rate on gross payroll
DA_RATE = 0.08


def month_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def paye_deadline(period: str) -> date:
    return month_end(period) + timedelta(days=10)


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.n = 0
        self.taxpayers: list[dict] = []
        self.employments: list[dict] = []
        self.returns: list[dict] = []
        self.payments: list[dict] = []
        self.legacy_taxpayers: list[dict] = []
        self.permits: list[dict] = []
        self.profiles: dict[str, str] = {}

    def tin(self) -> str:
        self.n += 1
        return f"SYN-{10000000 + self.n * 37:08d}"

    def person(self) -> str:
        return f"{self.r.choice(GIVEN)} {self.r.choice(FAMILY)}"

    def business(self) -> tuple[str, str]:
        b = self.r.choice(BIZ_B)
        return f"{self.r.choice(BIZ_A)} {b} Ltd", SECTOR_OF[b]

    # ------------------------------------------------------------------------------------------
    def employers(self, n: int) -> None:
        weights = [("compliant", 55), ("late_filer", 12), ("non_filer", 8), ("underpayer", 10), ("income_drop", 6),
                   ("seasonal", 3), ("closed", 2), ("dormant", 2), ("misallocated", 2)]
        pool = [p for p, w in weights for _ in range(w)]
        for i in range(n):
            profile = pool[i % len(pool)] if i < len(pool) else self.r.choice(pool)
            name, sector = self.business()
            if profile == "seasonal":
                sector = "Agriculture"
            tin = self.tin()
            rec = {
                "source_record_id": f"BIZ-{i + 1:05d}", "taxpayer_type": "business", "name": name, "tin": tin,
                "cac_rc": f"SYN-RC{700000 + i}", "registration_status": "registered", "tax_residence": STATE,
                "lga": self.r.choice(LGAS), "sector": sector, "is_employer": True, "operating_status": "active",
                "registered_on": (date(2015, 1, 1) + timedelta(days=self.r.randint(0, 3000))).isoformat(),
            }
            if profile == "closed":
                rec["operating_status"], rec["closed_on"] = "closed", "2025-06-30"
            if profile == "dormant":
                rec["operating_status"] = "dormant"
            self.taxpayers.append(rec)
            self.profiles[tin] = profile
            self._paye_history(rec, profile)

    def _paye_history(self, rec: dict, profile: str) -> None:
        tin = rec["tin"]
        staff = self.r.randint(3, 80)
        avg = self.r.randint(80, 450) * 1000
        base = staff * avg
        stop_from = "2026-0" + str(self.r.randint(2, 6)) if profile == "non_filer" else None
        for period in PAYE_MONTHS:
            if profile == "closed" and period > "2025-06":
                break
            if profile == "dormant" and period >= "2026-01":
                break
            if stop_from and period >= stop_from:
                break
            month = int(period[5:])
            income = base * self.r.uniform(0.95, 1.05)
            if month == 12:
                income *= 1.2
            if profile == "seasonal" and month in (7, 8):
                income *= 0.4
            if profile == "income_drop" and period >= "2026-05":
                income *= 0.35
            income = round(income, 2)
            liability = round(income * PAYE_RATE, 2)
            deadline = paye_deadline(period)
            late = profile == "late_filer" and self.r.random() < 0.45
            filed = deadline + timedelta(days=self.r.randint(5, 45)) if late else deadline - timedelta(days=self.r.randint(0, 9))
            if filed > CUTOFF:
                continue  # not yet filed at extraction time
            self.returns.append({
                "source_record_id": f"PAYE-{tin[-8:]}-{period}", "tin": tin, "tax_type": "PAYE", "period": period,
                "filing_date": filed.isoformat(), "reported_income": f"{income:.2f}", "reported_amount": f"{liability:.2f}",
                "employee_count": staff,
            })
            paid = liability
            if profile == "underpayer" and period >= "2026-01":
                paid = round(liability * self.r.uniform(0.35, 0.7), 2)
            pay_date = filed + timedelta(days=self.r.randint(0, 3)) if not late else filed + timedelta(days=self.r.randint(1, 10))
            if pay_date > CUTOFF:
                continue
            if profile == "misallocated" and period >= "2026-01":
                self.payments.append({
                    "source_record_id": f"PAY-{tin[-8:]}-{period}", "tin": tin, "tax_type": "PAYE", "period": None,
                    "amount": f"{paid:.2f}", "payment_date": pay_date.isoformat(), "allocation_status": "unallocated",
                    "channel": "bank_branch",
                })
                continue
            if paid > 0:
                split = profile == "compliant" and self.r.random() < 0.2
                parts = [round(paid * 0.6, 2), round(paid - round(paid * 0.6, 2), 2)] if split else [paid]
                for k, amt in enumerate(parts):
                    self.payments.append({
                        "source_record_id": f"PAY-{tin[-8:]}-{period}-{k}", "tin": tin, "tax_type": "PAYE", "period": period,
                        "amount": f"{amt:.2f}", "payment_date": pay_date.isoformat(), "allocation_status": "allocated",
                        "channel": self.r.choice(["remita", "bank_branch", "pos", "web"]),
                    })

    def individuals(self, n_employees: int, n_self_employed: int) -> None:
        employers = [t for t in self.taxpayers if t["is_employer"] and t["operating_status"] != "closed"]
        for i in range(n_employees):
            tin = self.tin()
            emp = self.r.choice(employers)
            self.taxpayers.append({
                "source_record_id": f"IND-{i + 1:05d}", "taxpayer_type": "individual", "name": self.person(), "tin": tin,
                "nin": f"SYN{30000000000 + i * 7919}", "registration_status": "registered", "tax_residence": STATE,
                "lga": emp["lga"], "sector": emp["sector"], "is_employer": False, "self_employed": False,
                "operating_status": "active",
            })
            self.employments.append({
                "source_record_id": f"EMP-{i + 1:05d}", "employer_tin": emp["tin"], "employee_tin": tin,
                "start_date": (date(2018, 1, 1) + timedelta(days=self.r.randint(0, 2400))).isoformat(),
                "monthly_gross": f"{self.r.randint(70, 600) * 1000:.2f}",
            })
        pool = ["compliant"] * 70 + ["non_filer"] * 15 + ["underpayer"] * 10 + ["income_drop"] * 5
        for i in range(n_self_employed):
            tin = self.tin()
            profile = pool[i % len(pool)]
            self.profiles[tin] = profile
            self.taxpayers.append({
                "source_record_id": f"SE-{i + 1:05d}", "taxpayer_type": "individual", "name": self.person(), "tin": tin,
                "nin": f"SYN{40000000000 + i * 7919}", "registration_status": "registered", "tax_residence": STATE,
                "lga": self.r.choice(LGAS), "sector": self.r.choice(SECTORS), "is_employer": False, "self_employed": True,
                "operating_status": "active",
            })
            income = self.r.randint(1200, 15000) * 1000.0
            for year in (2023, 2024, 2025):
                if profile == "non_filer" and year == 2025:
                    break
                inc = income * self.r.uniform(0.9, 1.1)
                if profile == "income_drop" and year == 2025:
                    inc *= 0.3
                liability = round(inc * DA_RATE, 2)
                deadline = date(year + 1, 3, 31)
                filed = deadline - timedelta(days=self.r.randint(0, 60))
                self.returns.append({
                    "source_record_id": f"DA-{tin[-8:]}-{year}", "tin": tin, "tax_type": "DA", "period": str(year),
                    "filing_date": filed.isoformat(), "reported_income": f"{inc:.2f}", "reported_amount": f"{liability:.2f}",
                })
                paid = liability * (self.r.uniform(0.3, 0.6) if profile == "underpayer" and year == 2025 else 1)
                self.payments.append({
                    "source_record_id": f"DAPAY-{tin[-8:]}-{year}", "tin": tin, "tax_type": "DA", "period": str(year),
                    "amount": f"{paid:.2f}", "payment_date": (filed + timedelta(days=2)).isoformat(),
                    "allocation_status": "allocated", "channel": "web",
                })

    def unregistered(self, n: int) -> None:
        """Entities in an authorised business-permit dataset with no tax registration."""
        for i in range(n):
            name, sector = self.business()
            self.permits.append({
                "source_record_id": f"PERMIT-{i + 1:05d}", "taxpayer_type": "business", "name": name,
                "cac_rc": f"SYN-RC{900000 + i}", "registration_status": "unregistered", "tax_residence": STATE,
                "lga": self.r.choice(LGAS), "sector": sector, "is_employer": True, "operating_status": "active",
            })
        # One permit holder that operates outside the state: jurisdiction safeguard suppresses the signal.
        self.permits.append({
            "source_record_id": f"PERMIT-{n + 1:05d}", "taxpayer_type": "business", "name": "Abuja Road Haulage Ltd",
            "cac_rc": "SYN-RC999999", "registration_status": "unregistered", "tax_residence": "FC", "lga": "Suleja",
            "sector": "Transport", "is_employer": True, "operating_status": "active",
        })

    def duplicates(self, n: int) -> None:
        """Same businesses registered again in a legacy system with name variants."""
        for i, src in enumerate([t for t in self.taxpayers if t["taxpayer_type"] == "business"][:n]):
            variant = src["name"].replace(" Ltd", " Limited") if i % 2 == 0 else src["name"].upper().replace(" LTD", " NIG LTD")
            self.legacy_taxpayers.append({**src, "source_record_id": f"LEG-{i + 1:05d}", "name": variant})

    def invalid_rows(self) -> None:
        self.returns += [
            {"source_record_id": "PAYE-BAD-001", "tin": self.taxpayers[0]["tin"], "tax_type": "PAYE", "period": "2026-13",
             "filing_date": "2026-02-01", "reported_income": "100.00", "reported_amount": "7.00"},
            {"source_record_id": "PAYE-BAD-002", "tin": self.taxpayers[1]["tin"], "tax_type": "PAYE", "period": "2026-01",
             "filing_date": "2026-02-01", "reported_income": "-5.00", "reported_amount": "7.00"},
            {"source_record_id": "PAYE-ORPHAN-001", "tin": "SYN-99999999", "tax_type": "PAYE", "period": "2026-01",
             "filing_date": "2026-02-05", "reported_income": "1500000.00", "reported_amount": "105000.00"},
            {"source_record_id": "PAYE-ORPHAN-002", "tin": "SYN-99999998", "tax_type": "PAYE", "period": "2026-02",
             "filing_date": "2026-03-05", "reported_income": "900000.00", "reported_amount": "63000.00"},
        ]
        self.returns.append(dict(self.returns[0]))  # exact duplicate row in the same batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "niger-pilot"))
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    g = Gen(args.seed)
    g.employers(120)
    g.individuals(240, 60)
    g.unregistered(10)
    g.duplicates(6)
    g.invalid_rows()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    batches = [
        ("01_taxpayers_register.json", "taxpayers", "NG-SIRS-REGISTER", g.taxpayers),
        ("02_taxpayers_permits.json", "taxpayers", "NG-BUSINESS-PERMITS", g.permits),
        ("03_taxpayers_legacy.json", "taxpayers", "NG-SIRS-LEGACY", g.legacy_taxpayers),
        ("04_employments.json", "employments", "NG-PAYE-PORTAL", g.employments),
        ("05_returns.json", "returns", "NG-PAYE-PORTAL", g.returns),
        ("06_payments.json", "payments", "NG-COLLECTIONS", g.payments),
    ]
    manifest = []
    for fname, dataset, source, records in batches:
        (out / fname).write_text(json.dumps(records, indent=1))
        manifest.append({"file": fname, "dataset": dataset, "source_system": source, "extracted_at": EXTRACTED_AT,
                         "records": len(records)})
    (out / "manifest.json").write_text(json.dumps({
        "synthetic": True, "state": "Niger State (pilot, fictional data)", "seed": args.seed,
        "notice": "All names, businesses and identifiers are fictional. SYN-prefixed identifiers only.",
        "batches": manifest, "profiles": g.profiles,
    }, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
