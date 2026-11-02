"""Facts for every configured revenue head (beyond PAYE).

Produces two fact kinds:

- ``account_period``: one record per revenue-head account and period (month, tax year, or the month of a
  recorded transaction), saying what was due, what was filed, served or recorded, and what was paid.
- ``taxpayer_profile``: one record per individual in the register who holds revenue-head accounts, used for
  cross-tax checks (business premises, commercial property or vehicles without a direct-assessment return).

The same safeguards as PAYE apply: only system-of-record sources count, unknown legal parameters make the
obligation *pending verification* (a hold), a demand creates a payment obligation only once served, and
coverage is checked per head and period.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from risk_engine import heads as head_patterns
from risk_engine.facts import FactRecord

from ..models import RevenueAccount, RevenueLiability, RevenuePayment, Taxpayer
from . import legal

if TYPE_CHECKING:
    from .facts import FactsContext

HEAD_FEEDS = ["revenue_account", "revenue_liability", "revenue_payment"]
RETURN_SUFFIXES = {"MONTHLY_RETURN", "ANNUAL_RETURN", "TRANSACTION"}
PAYMENT_SUFFIXES = {"MONTHLY_PAYMENT", "ANNUAL_PAYMENT", "DEMAND", "RENEWAL", "ANNUAL_LEVY", "TRANSACTION"}
RETURN_PATTERNS = {"monthly_return_payment", "annual_return_payment", "transaction"}
INCOME_USE = {None, "commercial", "mixed", "industrial"}


def _iso(d: datetime | None, ctx: FactsContext) -> str | None:
    return d.astimezone(ctx.tz).isoformat() if d else None


def _days_late(event: datetime | None, due: datetime | None) -> int | None:
    if event is None or due is None:
        return None
    return max(0, math.ceil((event - due).total_seconds() / 86400))


def _money(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


class HeadContext:
    def __init__(self, ctx: FactsContext):
        self.ctx = ctx
        db = ctx.db
        settings = ctx.tenant.settings or {}
        self.heads: dict[str, dict[str, Any]] = {h["code"]: h for h in settings.get("tax_heads", [])}
        self.accounts = [
            a
            for a in db.execute(select(RevenueAccount).where(RevenueAccount.is_current)).scalars()
            if a.tax_head in self.heads
        ]
        self.liabilities: dict[tuple[str, str], list[RevenueLiability]] = defaultdict(list)
        self.liability_periods: dict[str, set[str]] = defaultdict(set)
        for li in db.execute(select(RevenueLiability).where(RevenueLiability.is_current)).scalars():
            if li.source_name in ctx.sor_sources and li.tax_head in self.heads:
                self.liabilities[(li.account_ref, li.period_code)].append(li)
                self.liability_periods[li.account_ref].add(li.period_code)
        self.payments: dict[tuple[str, str], list[RevenuePayment]] = defaultdict(list)
        self.unallocated: set[str] = set()
        for p in db.execute(
            select(RevenuePayment).where(RevenuePayment.is_current, RevenuePayment.paid_at <= ctx.as_of)
        ).scalars():
            if p.source_name not in ctx.sor_sources or p.tax_head not in self.heads:
                continue
            if p.allocation_status == "allocated" and p.account_ref and p.period_code:
                self.payments[(p.account_ref, p.period_code)].append(p)
            elif p.account_ref and p.reversal_status != "reversed":
                self.unallocated.add(p.account_ref)
        self.taxpayers = {
            t.source_taxpayer_id: t for t in db.execute(select(Taxpayer).where(Taxpayer.is_current)).scalars()
        }
        self.years = sorted({p[:4] for p in ctx.periods})
        self._legal: dict[tuple[str, str], Any] = {}

    def version(self, code: str, period: str) -> Any:
        key = (code, period)
        if key not in self._legal:
            self._legal[key] = legal.resolve(self.ctx.db, code, period)
        return self._legal[key]

    def periods_for(self, a: RevenueAccount, pattern: str) -> list[str]:
        freq = head_patterns.PATTERNS[pattern].frequency
        if freq == "monthly":
            return list(self.ctx.periods)
        if freq == "annual":
            return list(self.years)
        return sorted(p for p in self.liability_periods.get(a.account_ref, set()) if p in self.ctx.periods)


def _identity(hc: HeadContext, a: RevenueAccount) -> tuple[bool, float, list[str]]:
    if a.taxpayer_ref and a.taxpayer_ref in hc.taxpayers:
        return True, 1.0, [f"src:taxpayer:{a.taxpayer_ref}"]
    if a.employer_ref:
        return hc.ctx.identity_quality(a.employer_ref)
    return False, 0.0, []


def _obligation_status(hc: HeadContext, a: RevenueAccount, period: str, codes: list[str]) -> str:
    start, end = legal.period_bounds(period)
    if a.status == "ceased" or (a.effective_to is not None and a.effective_to < start):
        return "ceased"
    if a.status == "exempt":
        return "ceased"
    if a.effective_from is not None and a.effective_from > end:
        return "none"
    if a.status == "pending_verification":
        return "pending_verification"
    if any(hc.version(c, period) is None for c in codes):
        return "pending_verification"
    return "active"


def _account_period(hc: HeadContext, a: RevenueAccount, period: str) -> FactRecord:
    ctx = hc.ctx
    head = hc.heads[a.tax_head]
    pattern = head["pattern"]
    codes = head_patterns.obligation_codes(a.tax_head, pattern)
    status = _obligation_status(hc, a, period, codes)
    items = hc.liabilities.get((a.account_ref, period), [])
    returns = [x for x in items if x.kind == "return" and x.status in ("filed", "accepted")]
    transactions = [x for x in items if x.kind == "transaction" and x.status == "recorded"]
    demands = [x for x in items if x.kind == "demand" and x.status in ("issued", "served")]
    served = [
        x for x in demands if x.status == "served" and x.event_date and x.event_date <= ctx.as_of.date()
    ]
    renewals = [x for x in items if x.kind == "renewal_due"]
    levies = [x for x in items if x.kind == "levy"]
    pays = hc.payments.get((a.account_ref, period), [])
    settled = [p for p in pays if p.reversal_status == "none" and p.settlement_status == "settled"]

    legal_versions: dict[str, dict[str, str]] = {}
    return_due: datetime | None = None
    pay_due: datetime | None = None
    tx_event = max((x.event_date for x in transactions if x.event_date), default=None)
    for code in codes:
        v = hc.version(code, period)
        if v is None:
            continue
        label = {"id": str(v.id), "label": f"{v.code}@{v.version}"}
        legal_versions[code] = label
        suffix = code[len(a.tax_head) + 1 :]
        event: date | None = None
        if suffix == "TRANSACTION":
            event = tx_event
        elif suffix == "DEMAND":
            event = min((x.event_date for x in served if x.event_date), default=None)
        elif suffix == "RENEWAL":
            event = min((x.event_date for x in renewals if x.event_date), default=None)
        due = legal.head_due(code, period, v.parameters, ctx.tz, event)
        if suffix in RETURN_SUFFIXES:
            return_due = due
            legal_versions["*:return"] = label
        if suffix in PAYMENT_SUFFIXES:
            pay_due = due
            legal_versions["*:payment"] = label

    filed_at = min((x.filed_at for x in returns if x.filed_at), default=None)
    if pattern in ("monthly_return_payment", "annual_return_payment"):
        established = bool(returns)
        amounts = [x.amount for x in returns if x.amount is not None]
    elif pattern == "transaction":
        # Payment is due on the declared amount; an undeclared transaction is FIL-102, not a payment signal.
        established = bool(transactions) and bool(returns)
        amounts = [x.amount for x in returns if x.amount is not None]
    elif pattern == "annual_demand":
        established = bool(served)
        amounts = [x.amount for x in served if x.amount is not None]
    elif pattern == "licence_renewal":
        established = bool(renewals)
        amounts = [x.amount for x in renewals if x.amount is not None]
    else:  # annual_levy: the levy applies to every active account
        established = True
        amounts = [x.amount for x in levies if x.amount is not None]
    amount = float(sum(amounts, Decimal("0"))) if amounts else None
    paid_total = float(sum((p.amount for p in settled), Decimal("0")))
    first_paid = min((p.paid_at for p in settled), default=None)
    _, end = legal.period_bounds(period)
    area = a.area_code
    hold = (
        any(x.appeal_status in ("appealed", "stayed") for x in items)
        or (
            a.account_ref,
            period,
        )
        in ctx.legal_holds
    )
    facts: dict[str, Any] = {
        "anchor_period": False,
        "obligation_status": status,
        "pattern": pattern,
        "subject_type": a.subject_type,
        "use_class": a.use_class or "unknown",
        "period_closed": legal.end_of_day(end, ctx.tz) < ctx.as_of,
        "return_required": pattern in RETURN_PATTERNS,
        "return_due_at": _iso(return_due, ctx),
        "return_due_passed": bool(return_due and ctx.as_of > return_due),
        "filed_count": len({x.liability_ref for x in returns}),
        "filed_at": _iso(filed_at, ctx),
        "filing_late_days": _days_late(filed_at, return_due),
        "transaction_count": len(transactions),
        "demand_issued": bool(demands) if pattern == "annual_demand" else bool(levies),
        "demand_served": bool(served),
        "liability_established": established,
        "liability_amount": amount,
        "payment_due_at": _iso(pay_due, ctx),
        "payment_due_passed": bool(pay_due and ctx.as_of > pay_due),
        "paid_total": paid_total,
        "settled_payment_count": len(settled),
        "first_payment_at": _iso(first_paid, ctx),
        "payment_late_days": _days_late(first_paid, pay_due),
        "residual_amount": None if amount is None else round(amount - paid_total, 2),
        "reversal_pending": any(p.reversal_status == "reversal_pending" for p in pays),
        "possible_unallocated_receipt": a.account_ref in hc.unallocated,
        "legal_hold": hold,
        "disputed": (a.account_ref, period) in ctx.disputed,
    }
    verified, confidence, id_refs = _identity(hc, a)
    liab_refs = [f"src:revenue_liability:{x.natural_key}" for x in items]
    pay_refs = [f"src:revenue_payment:{p.natural_key}" for p in pays]
    evidence = {
        "_subject": [f"src:revenue_account:{a.account_ref}", *id_refs],
        "_obligation": [f"legal:{v['label']}" for k, v in legal_versions.items() if not k.startswith("*")],
        "filed_count": [f"src:revenue_liability:{x.natural_key}" for x in returns] or liab_refs,
        "filing_late_days": [f"src:revenue_liability:{x.natural_key}" for x in returns],
        "transaction_count": [f"src:revenue_liability:{x.natural_key}" for x in transactions],
        "demand_issued": [f"src:revenue_liability:{x.natural_key}" for x in demands],
        "demand_served": [f"src:revenue_liability:{x.natural_key}" for x in served],
        "liability_amount": liab_refs,
        "settled_payment_count": pay_refs,
        "paid_total": pay_refs,
        "residual_amount": liab_refs + pay_refs,
        "payment_late_days": pay_refs,
    }
    return {
        "kind": "account_period",
        "subject_type": "account",
        "subject_id": a.account_ref,
        "period": period,
        "tax_type": a.tax_head,
        "tax_head_name": head.get("name"),
        "facts": facts,
        "quality": {
            "identity_verified": verified,
            "match_confidence": confidence,
            "staleness_days": ctx.staleness(HEAD_FEEDS),
            "freshness_sla_days": ctx.sla,
            "coverage": {
                "filing": ctx.covered(f"revenue_liability:{a.tax_head}", period, area),
                "payment": ctx.covered(f"revenue_payment:{a.tax_head}", period, area),
            },
        },
        "evidence": evidence,
        "legal_versions": legal_versions,
        "area_code": area,
        "employer_ref": a.employer_ref,
        "taxpayer_ref": a.taxpayer_ref,
        "account_name": a.display_name,
    }


def _history(series: list[FactRecord]) -> None:
    hist_f: list[dict[str, Any]] = []
    hist_p: list[dict[str, Any]] = []
    anchor = None
    for r in series:
        f, cov = r["facts"], r["quality"]["coverage"]
        active = f["obligation_status"] == "active"
        f_elig = active and f["return_required"] and f["return_due_passed"] and cov["filing"]
        p_elig = (
            active
            and f["liability_established"]
            and f["payment_due_passed"]
            and cov["payment"]
            and not f["possible_unallocated_receipt"]
        )
        hist_f.append(
            {
                "period": r["period"],
                "eligible": bool(f_elig),
                "missing": bool(f_elig and f["filed_count"] == 0),
                "late": bool(active and cov["filing"] and (f["filing_late_days"] or 0) > 0),
            }
        )
        hist_p.append(
            {
                "period": r["period"],
                "eligible": bool(p_elig),
                "missing": bool(p_elig and f["settled_payment_count"] == 0),
                "late": bool(active and cov["payment"] and (f["payment_late_days"] or 0) > 0),
            }
        )
        r["history"] = {"filing": list(hist_f), "payment": list(hist_p)}
        if f["return_due_passed"] or f["payment_due_passed"]:
            anchor = r
    if anchor is not None:
        anchor["facts"]["anchor_period"] = True


def _taxpayer_profiles(hc: HeadContext) -> list[FactRecord]:
    """Cross-tax view of individuals: income indicators against direct-assessment filing."""
    ctx = hc.ctx
    da_heads = [
        c
        for c, h in hc.heads.items()
        if h["pattern"] == "annual_return_payment" and h["subject_type"] == "individual"
    ]
    if not da_heads:
        return []
    da = da_heads[0]
    return_code = f"{da}_ANNUAL_RETURN"
    tax_year = None
    for y in hc.years:
        v = hc.version(return_code, y)
        if v is None:
            continue
        due = legal.head_due(return_code, y, v.parameters, ctx.tz)
        if due is not None and due < ctx.as_of:
            tax_year = y
    if tax_year is None:  # no tax year whose return is due under an approved version: nothing to compare
        return []
    by_taxpayer: dict[str, list[RevenueAccount]] = defaultdict(list)
    for a in hc.accounts:
        if a.taxpayer_ref:
            by_taxpayer[a.taxpayer_ref].append(a)
    out: list[FactRecord] = []
    for ref in sorted(by_taxpayer):
        tp = hc.taxpayers.get(ref)
        if tp is None:
            continue
        accts = by_taxpayer[ref]
        indicators = [
            a
            for a in accts
            if a.status == "active"
            and hc.heads[a.tax_head].get("indicates_income")
            and (a.use_class in INCOME_USE)
        ]
        da_accounts = [a for a in accts if a.tax_head == da]
        filed = False
        refs: list[str] = []
        if tax_year is not None:
            for a in da_accounts:
                rets = [
                    x
                    for x in hc.liabilities.get((a.account_ref, tax_year), [])
                    if x.kind == "return" and x.status in ("filed", "accepted")
                ]
                refs += [f"src:revenue_liability:{x.natural_key}" for x in rets]
                filed = filed or bool(rets)
        legal_versions: dict[str, dict[str, str]] = {}
        if tax_year is not None:
            v = hc.version(return_code, tax_year)
            if v is not None:
                legal_versions = {
                    return_code: {"id": str(v.id), "label": f"{v.code}@{v.version}"},
                    "*:return": {"id": str(v.id), "label": f"{v.code}@{v.version}"},
                }
        out.append(
            {
                "kind": "taxpayer_profile",
                "subject_type": "taxpayer",
                "subject_id": ref,
                "period": tax_year,
                "tax_type": da,
                "tax_head_name": hc.heads[da].get("name"),
                "facts": {
                    "taxpayer_type": tp.taxpayer_type,
                    "taxpayer_status": tp.status,
                    "income_indicator_count": len(indicators),
                    "income_indicator_heads": ", ".join(sorted({a.tax_head for a in indicators})) or "none",
                    "has_direct_assessment_account": bool(da_accounts),
                    "tax_year": tax_year,
                    "tax_year_due_passed": tax_year is not None,
                    "direct_assessment_filed": filed,
                    "legal_hold": (ref, tax_year) in ctx.legal_holds,
                    "disputed": (ref, tax_year) in ctx.disputed,
                },
                "quality": {
                    "identity_verified": True,
                    "match_confidence": 1.0,
                    "staleness_days": ctx.staleness(HEAD_FEEDS),
                    "freshness_sla_days": ctx.sla,
                    "coverage": {},
                },
                "evidence": {
                    "_subject": [f"src:taxpayer:{ref}"],
                    "income_indicator_count": [f"src:revenue_account:{a.account_ref}" for a in indicators],
                    "direct_assessment_filed": refs
                    or [f"src:revenue_account:{a.account_ref}" for a in da_accounts],
                },
                "legal_versions": legal_versions,
                "area_code": tp.area_code,
                "taxpayer_ref": ref,
                "account_name": tp.display_name,
            }
        )
    return out


def build(ctx: FactsContext) -> list[FactRecord]:
    hc = HeadContext(ctx)
    if not hc.heads:
        return []
    records: list[FactRecord] = []
    for a in sorted(hc.accounts, key=lambda x: (x.tax_head, x.account_ref)):
        pattern = hc.heads[a.tax_head]["pattern"]
        series = [_account_period(hc, a, p) for p in hc.periods_for(a, pattern)]
        _history(series)
        records.extend(series)
    records.extend(_taxpayer_profiles(hc))
    return records
