"""NFR-03 engine throughput check: evaluate the pilot pack over N synthetic employer-period records.

    uv run python -m scripts.benchmark_engine --records 100000

Measures the deterministic engine only (fact building and persistence scale with the database and are
measured separately in shadow mode on agreed deployment sizing).
"""

from __future__ import annotations

import argparse
import random
import time

from risk_engine import evaluate, load_pilot_pack
from tests.unit.helpers import employer_period


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100_000)
    args = parser.parse_args()
    rng = random.Random(7)
    rules = [r for r in load_pilot_pack() if r.scope.fact_kind == "employer_period"]
    records = []
    for i in range(args.records):
        hist = [
            {"period": f"p{j}", "eligible": True, "missing": rng.random() < 0.1, "late": rng.random() < 0.1}
            for j in range(12)
        ]
        records.append(
            employer_period(
                period=f"2026-{(i % 12) + 1:02d}",
                history={"filing": hist, "payment": hist},
                accepted_filing_count=int(rng.random() > 0.05),
                filing_late_days=rng.choice([0, 0, 0, 3]),
                settled_payment_count=int(rng.random() > 0.05),
                payment_late_days=rng.choice([0, 0, 0, 2]),
                declared_payable=float(rng.randrange(50_000, 5_000_000)),
                residual_amount=rng.choice([0.0, 0.0, 25_000.0]),
                anchor_period=i % 12 == 11,
                staleness_days=rng.choice([1, 2, 3, 9]),
            )
        )
    start = time.perf_counter()
    triggered = 0
    for rec in records:
        for rule in rules:
            triggered += evaluate(rule, rec).is_finding
    elapsed = time.perf_counter() - start
    evaluations = len(records) * len(rules)
    print(
        f"{len(records):,} employer-periods x {len(rules)} rules = {evaluations:,} evaluations "
        f"in {elapsed:.1f}s ({evaluations / elapsed:,.0f}/s); {triggered:,} findings. "
        f"NFR-03 target: 100,000 employer-periods within 1,800s."
    )


if __name__ == "__main__":
    main()
