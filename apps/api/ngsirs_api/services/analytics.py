"""Dashboard metrics with numerator, denominator, window and completeness (FR-014).

Compliance rates are computed from the latest operational evaluation snapshot,
so the denominators match exactly what the engine considered eligible. Rates
are withheld (value = None) when coverage is too low to be meaningful, and
confirmed arrears are never mixed with estimates.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from risk_engine.states import OPEN_FINDING_STATES

from ..models import (
    Assessment,
    CaseRecord,
    DataSource,
    EvaluationRun,
    IdentityMatch,
    IngestBatch,
    InputSnapshot,
    Lga,
    RiskFinding,
    SourceRecord,
)
from .evaluation import load_snapshot

MIN_COMPLETENESS = 0.8


def metric(
    key: str,
    label: str,
    numerator: float | None,
    denominator: float | None,
    window: str,
    completeness: float | None,
    unit: str = "rate",
    caveats: list[str] | None = None,
    value: float | None = None,
) -> dict[str, Any]:
    caveats = list(caveats or [])
    if value is None and unit == "rate":
        if denominator:
            value = round((numerator or 0) / denominator, 4)
        else:
            caveats.append("No eligible population in window")
    if unit == "rate" and completeness is not None and completeness < MIN_COMPLETENESS and value is not None:
        caveats.append(f"Data completeness {completeness:.0%} is below {MIN_COMPLETENESS:.0%}; rate withheld")
        value = None
    if value is None and unit != "rate":
        value = numerator
    return {
        "key": key,
        "label": label,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "window": window,
        "completeness": completeness,
        "unit": unit,
        "caveats": caveats,
    }


def latest_run(db: Session) -> EvaluationRun | None:
    return (
        db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.mode == "operational", EvaluationRun.status == "completed")
            .order_by(EvaluationRun.finished_at.desc())
        )
        .scalars()
        .first()
    )


def _employer_records(db: Session, run: EvaluationRun) -> list[dict[str, Any]]:
    snap = db.get(InputSnapshot, run.snapshot_id)
    assert snap is not None
    return [r for r in load_snapshot(snap) if r["kind"] == "employer_period"]  # type: ignore[misc]


def filing_rates(
    records: list[dict[str, Any]],
    period: str | None = None,
    lga: str | None = None,
    group: set[str] | None = None,
) -> dict[str, Any]:
    """On-time filing among employers with an active, due, coverage-complete obligation."""
    obligated = eligible = on_time = 0
    for r in records:
        if period and r["period"] != period:
            continue
        if lga and r.get("lga_code") != lga:
            continue
        if group is not None and r["subject_id"] not in group:
            continue
        f, q = r["facts"], r["quality"]
        if f["obligation_status"] != "active" or not f["return_due_passed"]:
            continue
        obligated += 1
        if not q["coverage"]["filing"] or f["source_conflict"]:
            continue
        eligible += 1
        if f["accepted_filing_count"] > 0 and (f["filing_late_days"] or 0) == 0:
            on_time += 1
    completeness = round(eligible / obligated, 4) if obligated else None
    return {
        "numerator": on_time,
        "denominator": eligible,
        "obligated": obligated,
        "completeness": completeness,
    }


def remittance_rates(
    records: list[dict[str, Any]], period: str | None = None, lga: str | None = None
) -> dict[str, Any]:
    obligated = eligible = on_time = 0
    for r in records:
        if period and r["period"] != period:
            continue
        if lga and r.get("lga_code") != lga:
            continue
        f, q = r["facts"], r["quality"]
        if f["obligation_status"] != "active" or not f["payment_due_passed"]:
            continue
        obligated += 1
        if not q["coverage"]["payment"] or f["possible_unallocated_receipt"] or f["source_conflict"]:
            continue
        eligible += 1
        if f["settled_payment_count"] > 0 and (f["payment_late_days"] or 0) == 0:
            on_time += 1
    completeness = round(eligible / obligated, 4) if obligated else None
    return {
        "numerator": on_time,
        "denominator": eligible,
        "obligated": obligated,
        "completeness": completeness,
    }


def summary(db: Session, period: str | None, lga: str | None) -> dict[str, Any]:
    run = latest_run(db)
    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic_data": True,
        "filters": {"period": period, "lga": lga, "tax_type": "PAYE"},
        "run": None,
        "metrics": [],
        "trend": [],
        "by_lga": [],
        "findings": {},
        "cases": {},
        "data_quality": {},
    }
    if run is not None:
        records = _employer_records(db, run)
        periods = sorted({r["period"] for r in records})
        due_periods = [
            p for p in periods if any(r["period"] == p and r["facts"]["return_due_passed"] for r in records)
        ]
        period = period or (due_periods[-1] if due_periods else None)
        out["filters"]["period"] = period
        out["run"] = {
            "id": str(run.id),
            "as_of": run.as_of.isoformat(),
            "rule_set_hash": run.rule_set_hash,
            "periods": [run.period_from, run.period_to],
        }
        fr = filing_rates(records, period, lga)
        rr = remittance_rates(records, period, lga)
        window = f"Tax period {period}; evaluated as at {run.as_of:%Y-%m-%d}"
        out["metrics"] += [
            metric(
                "paye_on_time_filing",
                "PAYE returns accepted on time",
                fr["numerator"],
                fr["denominator"],
                window,
                fr["completeness"],
                caveats=[
                    f"Denominator: {fr['denominator']} of {fr['obligated']} obligated employers with "
                    "complete filing coverage"
                ],
            ),
            metric(
                "paye_on_time_remittance",
                "PAYE remittances settled on time",
                rr["numerator"],
                rr["denominator"],
                window,
                rr["completeness"],
                caveats=[
                    f"Denominator: {rr['denominator']} of {rr['obligated']} obligated employers with "
                    "complete, reconciled payment coverage"
                ],
            ),
        ]
        for p in due_periods:
            f2 = filing_rates(records, p, lga)
            r2 = remittance_rates(records, p, lga)
            out["trend"].append(
                {
                    "period": p,
                    "filing": metric(
                        "filing", "On-time filing", f2["numerator"], f2["denominator"], p, f2["completeness"]
                    ),
                    "remittance": metric(
                        "remittance",
                        "On-time remittance",
                        r2["numerator"],
                        r2["denominator"],
                        p,
                        r2["completeness"],
                    ),
                }
            )
        lga_names = {lg.code: lg.name for lg in db.execute(select(Lga)).scalars()}
        for code in sorted({r.get("lga_code") for r in records if r.get("lga_code")}):
            f3 = filing_rates(records, period, code)
            if not f3["obligated"]:
                continue
            out["by_lga"].append(
                {
                    "lga": code,
                    "name": lga_names.get(code, code),
                    "filing": metric(
                        "filing",
                        "On-time filing",
                        f3["numerator"],
                        f3["denominator"],
                        period or "",
                        f3["completeness"],
                    ),
                }
            )

    fq = select(RiskFinding).where(
        RiskFinding.status.in_(OPEN_FINDING_STATES), RiskFinding.superseded_by_id.is_(None)
    )
    if lga:
        fq = fq.where(RiskFinding.lga_code == lga)
    open_findings = list(db.execute(fq).scalars())
    out["findings"] = {
        "open": len(open_findings),
        "by_class": dict(Counter(f.signal_class for f in open_findings)),
        "by_rule": dict(sorted(Counter(f.rule_code for f in open_findings).items())),
        "by_band": dict(
            Counter(f.priority_band or ("data_hold" if f.data_hold else "unscored") for f in open_findings)
        ),
        "data_holds": sum(1 for f in open_findings if f.data_hold),
        "legal_holds": sum(1 for f in open_findings if f.legal_hold),
        "disputed": sum(1 for f in open_findings if f.disputed),
    }
    reviewed = Counter(
        s
        for s in db.execute(
            select(RiskFinding.status).where(
                RiskFinding.status.in_(["closed_confirmed", "closed_not_substantiated"])
            )
        ).scalars()
    )
    total_reviewed = reviewed["closed_confirmed"] + reviewed["closed_not_substantiated"]
    out["metrics"].append(
        metric(
            "false_positive_rate",
            "Findings not substantiated on review",
            reviewed["closed_not_substantiated"],
            total_reviewed,
            "All closed findings to date",
            None,
            caveats=["Shadow-mode baseline; small samples are unstable"] if total_reviewed < 30 else [],
        )
    )

    served = [
        a
        for a in db.execute(
            select(Assessment).where(Assessment.is_current, Assessment.status == "served")
        ).scalars()
        if a.outstanding_amount > 0
    ]
    confirmed = sum(
        (a.outstanding_amount for a in served if a.appeal_status not in ("appealed", "stayed")), Decimal("0")
    )
    held = sum(
        (a.outstanding_amount for a in served if a.appeal_status in ("appealed", "stayed")), Decimal("0")
    )
    out["metrics"] += [
        metric(
            "confirmed_arrears",
            "Confirmed assessed arrears (served, not under appeal or stay)",
            float(confirmed),
            None,
            "Current balances",
            None,
            unit="NGN",
            caveats=[
                "Confirmed served assessments only. Excludes estimates and unreconciled remittance gaps."
            ],
        ),
        metric(
            "arrears_under_hold",
            "Assessed balances under appeal or stay",
            float(held),
            None,
            "Current balances",
            None,
            unit="NGN",
            caveats=["Not collectable while the hold applies"],
        ),
    ]

    cases = list(db.execute(select(CaseRecord)).scalars())
    now = datetime.now(UTC)
    first_action_days = []
    findings_by_id = (
        {
            f.id: f
            for f in db.execute(
                select(RiskFinding).where(RiskFinding.id.in_([c.finding_id for c in cases]))
            ).scalars()
        }
        if cases
        else {}
    )
    for c in cases:
        f = findings_by_id.get(c.finding_id)
        if c.approved_at and f is not None:
            first_action_days.append((c.approved_at - f.created_at).total_seconds() / 86400)
    out["cases"] = {
        "by_stage": dict(Counter(c.stage for c in cases)),
        "overdue": sum(
            1 for c in cases if c.stage not in ("closed", "rejected") and c.due_at and c.due_at < now
        ),
        "outward_permitted": sum(1 for c in cases if c.outward_permitted),
    }
    out["metrics"].append(
        metric(
            "median_days_to_action",
            "Median days from trigger to approved first action",
            round(statistics.median(first_action_days), 2) if first_action_days else None,
            len(first_action_days),
            "All approved cases",
            None,
            unit="days",
        )
    )

    pending_matches = db.execute(
        select(func.count()).select_from(IdentityMatch).where(IdentityMatch.status == "pending_review")
    ).scalar_one()
    quarantined = db.execute(
        select(func.count())
        .select_from(SourceRecord)
        .where(SourceRecord.status == "quarantined", SourceRecord.resolution.is_(None))
    ).scalar_one()
    out["data_quality"] = {
        "quarantined_unresolved": quarantined,
        "identity_matches_pending": pending_matches,
        "sources": source_freshness(db),
    }
    return out


def source_freshness(db: Session) -> list[dict[str, Any]]:
    out = []
    now = datetime.now(UTC)
    latest: dict[tuple[Any, str], IngestBatch] = {}
    for b in db.execute(select(IngestBatch).where(IngestBatch.qa_status == "committed")).scalars():
        k = (b.source_id, b.feed_type)
        if k not in latest or b.extracted_at > latest[k].extracted_at:
            latest[k] = b
    for s in db.execute(select(DataSource).order_by(DataSource.source_name)).scalars():
        for feed in s.feed_types:
            b = latest.get((s.id, feed))
            age = (now - b.extracted_at).days if b else None
            out.append(
                {
                    "source": s.source_name,
                    "feed_type": feed,
                    "last_extracted_at": b.extracted_at.isoformat() if b else None,
                    "age_days": age,
                    "sla_days": s.freshness_sla_days,
                    "stale": age is None or age > s.freshness_sla_days,
                }
            )
    return out


def lga_breakdown_rows(db: Session, period: str | None) -> list[dict[str, Any]]:
    run = latest_run(db)
    if run is None:
        return []
    records = _employer_records(db, run)
    rows = []
    by_lga: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_lga[r.get("lga_code") or "unknown"].append(r)
    for code, recs in sorted(by_lga.items()):
        fr = filing_rates(recs, period)
        rr = remittance_rates(recs, period)
        rows.append(
            {
                "lga": code,
                "period": period or "all",
                "filing_on_time": fr["numerator"],
                "filing_denominator": fr["denominator"],
                "filing_obligated": fr["obligated"],
                "filing_completeness": fr["completeness"],
                "remittance_on_time": rr["numerator"],
                "remittance_denominator": rr["denominator"],
                "remittance_completeness": rr["completeness"],
            }
        )
    return rows
