"""Metric catalogue (FR-08, PRD §8). Every figure ships with its definition, numerator,
denominator, coverage and data freshness so it can be reconciled to source."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Case, Payment, RiskAssessment, Taxpayer, TaxObligation, TaxReturn
from .obligations import _in_scope
from .scoring import DEFAULT_THRESHOLDS, feed_freshness

METRIC_VERSION = "1.0"

DEFINITIONS = {
    "timely_filing_rate": {
        "label": "Timely filing rate",
        "definition": "Returns filed by the legal deadline (incl. approved extensions) ÷ returns legally due among eligible active taxpayers, for obligations whose deadline has passed.",
    },
    "payment_compliance_rate": {
        "label": "Payment compliance rate (count)",
        "definition": "Obligations with declared liability fully paid (within tolerance) by the deadline ÷ obligations with declared liability past deadline.",
    },
    "payment_compliance_value": {
        "label": "Payment compliance rate (value)",
        "definition": "Value paid on time (capped at liability) ÷ total declared liability past deadline.",
    },
    "registration_coverage": {
        "label": "Registration coverage",
        "definition": "Registered taxpayers ÷ (registered + unregistered entities observed in authorised datasets). Denominator is an observed population, not a defensible liable-population estimate.",
        "caution": "Estimate quality LOW until a defensible liable-population estimate is agreed.",
    },
    "cases_within_sla": {
        "label": "Cases resolved within SLA",
        "definition": "Cases closed on or before their SLA due date ÷ closed cases. Read alongside case mix.",
    },
    "revenue_at_risk": {
        "label": "Revenue at risk (scenario)",
        "definition": "Sum of signal exposure estimates on current open/confirmed alerts. A scenario estimate from declared and historical figures — not collectible debt.",
        "caution": "Excludes taxpayers with no filing history; no confidence interval until back-testing.",
    },
}


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def compute(
    db: Session, tenant_id: uuid.UUID, *, period: str, tax_type: str | None, lga: str | None, sector: str | None, as_of: date,
) -> dict[str, Any]:
    tps = {
        t.id: t
        for t in db.execute(
            select(Taxpayer).where(Taxpayer.tenant_id == tenant_id, Taxpayer.merged_into_id.is_(None), Taxpayer.deleted_at.is_(None))
        ).scalars()
        if (lga is None or t.lga == lga) and (sector is None or t.sector == sector)
    }
    feeds = feed_freshness(db, tenant_id)
    returns_feed = date.fromisoformat(feeds["returns"]) if feeds.get("returns") else None

    q = select(TaxObligation).where(TaxObligation.tenant_id == tenant_id, TaxObligation.status != "exempt")
    if tax_type:
        q = q.where(TaxObligation.tax_type == tax_type)
    obs = [o for o in db.execute(q).scalars() if o.taxpayer_id in tps and _in_scope(o.period, period)]
    due = [o for o in obs if (o.extension_until or o.due_date) < as_of]

    filed_on_time = sum(1 for o in due if o.status == "filed")
    covered = sum(1 for o in due if returns_feed is not None and returns_feed > (o.extension_until or o.due_date))

    by_lga: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for o in due:
        key = tps[o.taxpayer_id].lga or "Unknown"
        by_lga[key][1] += 1
        by_lga[key][0] += int(o.status == "filed")

    ob_ids = [o.id for o in due]
    rets: dict[uuid.UUID, list[TaxReturn]] = defaultdict(list)
    pays: dict[uuid.UUID, list[Payment]] = defaultdict(list)
    if ob_ids:
        for r in db.execute(select(TaxReturn).where(TaxReturn.obligation_id.in_(ob_ids))).scalars():
            rets[r.obligation_id].append(r)
        for p in db.execute(select(Payment).where(Payment.obligation_id.in_(ob_ids), Payment.allocation_status == "allocated")).scalars():
            pays[p.obligation_id].append(p)
    tol = Decimal(str(DEFAULT_THRESHOLDS["payment_tolerance"]))
    pay_den = pay_num = 0
    val_due = val_paid = Decimal("0")
    for o in due:
        if not rets[o.id]:
            continue
        liability = max(rets[o.id], key=lambda r: (r.filing_date, r.created_at)).reported_amount
        if liability <= 0:
            continue
        deadline = o.extension_until or o.due_date
        on_time = sum((p.amount for p in pays[o.id] if p.payment_date <= deadline), Decimal("0"))
        pay_den += 1
        pay_num += int(on_time >= liability * (1 - tol))
        val_due += liability
        val_paid += min(on_time, liability)

    registered = sum(1 for t in tps.values() if t.registration_status == "registered")
    unregistered = sum(1 for t in tps.values() if t.registration_status == "unregistered")

    cq = select(Case).where(Case.tenant_id == tenant_id, Case.status == "closed")
    closed = [c for c in db.execute(cq).scalars() if c.taxpayer_id in tps]
    within = sum(1 for c in closed if c.closed_at and c.closed_at.date() <= c.sla_due)
    mix: dict[str, int] = defaultdict(int)
    for c in closed:
        mix[c.disposition or "unknown"] += 1
    collected = sum((c.amount_collected or Decimal("0") for c in closed), Decimal("0"))

    aq = select(Alert, RiskAssessment).join(RiskAssessment, RiskAssessment.id == Alert.assessment_id).where(
        Alert.tenant_id == tenant_id, Alert.status.in_(["open", "confirmed", "escalated", "data_verification"])
    )
    if tax_type:
        aq = aq.where(Alert.tax_type == tax_type)
    alert_rows = [(a, ra) for a, ra in db.execute(aq).all() if a.taxpayer_id in tps and _in_scope(a.period, period)]
    alert_status: dict[str, int] = defaultdict(int)
    for a, _ in alert_rows:
        alert_status[a.status] += 1
    rar = sum((ra.exposure_estimate for a, ra in alert_rows if a.status != "data_verification"), Decimal("0"))

    coverage = _ratio(covered, len(due))
    common = {"coverage": coverage, "freshness": feeds}

    def metric(key: str, num, den, value=None, **extra):
        return {"key": key, **DEFINITIONS[key], "numerator": num, "denominator": den,
                "value": value if value is not None else _ratio(float(num), float(den)), **common, **extra}

    return {
        "metric_version": METRIC_VERSION,
        "filters": {"period": period, "tax_type": tax_type, "lga": lga, "sector": sector, "as_of": as_of.isoformat()},
        "freshness": feeds,
        "metrics": [
            metric("timely_filing_rate", filed_on_time, len(due)),
            metric("payment_compliance_rate", pay_num, pay_den),
            metric("payment_compliance_value", str(val_paid), str(val_due), _ratio(float(val_paid), float(val_due))),
            metric("registration_coverage", registered, registered + unregistered, estimate_quality="low"),
            metric("cases_within_sla", within, len(closed), case_mix=dict(mix), amount_collected=str(collected)),
            metric("revenue_at_risk", str(rar), None, float(rar)),
        ],
        "breakdowns": {
            "timely_filing_by_lga": sorted(
                ({"lga": k, "numerator": v[0], "denominator": v[1], "value": _ratio(v[0], v[1])} for k, v in by_lga.items()),
                key=lambda x: x["lga"],
            ),
            "alerts_by_status": dict(alert_status),
        },
    }
