"""Facts builder: canonical NGSIRS data -> engine fact records.

This is where negative evidence is handled carefully (Tech Spec section 8.4):
a missing filing only counts as missing when accepted-filing coverage for the
period is complete; event time (accepted_at, paid_at) is used, never ingestion
time; unallocated receipts, quarantined rows, reversals and source conflicts
are surfaced as facts so rules can suppress or hold instead of accusing.

The output is plain JSON and is frozen into an input snapshot.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.facts import FactRecord
from risk_engine.states import OPEN_FINDING_STATES

from ..models import (
    Assessment,
    DataSource,
    Employer,
    Extension,
    IngestBatch,
    LegalRuleVersion,
    Payment,
    PaymentAllocation,
    PeriodSchedule,
    ReturnFiling,
    RiskFinding,
    SourceCoverage,
    SourceRecord,
    TaxObligation,
    Taxpayer,
    TaxpayerIdentifier,
    Tenant,
)
from . import identity, legal

RETURN_CODE = "PAYE_EMPLOYER_MONTHLY_RETURN"
REMIT_CODE = "PAYE_EMPLOYER_REMITTANCE"
ASSESS_CODE = "PAYE_ASSESSMENT"
EMPLOYER_FEEDS = ["ngsirs_employer", "ngsirs_obligation", "ngsirs_paye_return", "ngsirs_payment"]
ACTIVE_QUARANTINE = (None, "escalated")


def _days_late(event: datetime | None, due: datetime | None) -> int | None:
    if event is None or due is None:
        return None
    delta = (event - due).total_seconds()
    return max(0, math.ceil(delta / 86400))


def _iso(d: datetime | date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _money(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


class FactsContext:
    """Everything the builder needs, loaded once per evaluation."""

    def __init__(self, db: Session, tenant: Tenant, as_of: datetime, periods: list[str]):
        self.db, self.tenant, self.as_of, self.periods = db, tenant, as_of, periods
        cfg = tenant.settings or {}
        self.processing_window_days = int(cfg.get("processing_window_days", 5))
        self.employers = {
            e.source_employer_id: e for e in db.execute(select(Employer).where(Employer.is_current)).scalars()
        }
        self.matches = identity.latest_matches(db)
        self.obligations: dict[str, list[TaxObligation]] = defaultdict(list)
        for o in db.execute(select(TaxObligation).where(TaxObligation.is_current)).scalars():
            self.obligations[o.taxpayer_ref].append(o)
        self.schedules = {
            (s.legal_code, s.period_code): s for s in db.execute(select(PeriodSchedule)).scalars()
        }
        self.legal_versions = {v.id: v for v in db.execute(select(LegalRuleVersion)).scalars()}
        self.extensions: dict[tuple[str, str, str], Extension] = {}
        for x in db.execute(select(Extension).where(Extension.is_current)).scalars():
            self.extensions[(x.employer_ref, x.obligation_type, x.period_code)] = x
        self.filings: dict[tuple[str, str], list[ReturnFiling]] = defaultdict(list)
        for f in db.execute(select(ReturnFiling).where(ReturnFiling.is_current)).scalars():
            self.filings[(f.employer_ref, f.period_code)].append(f)
        # Only system-of-record sources count as evidence of filing/payment; secondary sources (bank feed,
        # legacy register) are used to detect conflicts, never to clear or create obligations.
        self.sor_sources = {
            s.source_name for s in db.execute(select(DataSource)).scalars() if s.system_of_record
        }
        all_payments = list(
            db.execute(select(Payment).where(Payment.is_current, Payment.paid_at <= as_of)).scalars()
        )
        self.payments = [p for p in all_payments if p.natural_key.split("|", 1)[0] in self.sor_sources]
        alloc: dict[uuid.UUID, list[PaymentAllocation]] = defaultdict(list)
        for a in db.execute(select(PaymentAllocation).where(PaymentAllocation.is_current)).scalars():
            alloc[a.payment_id].append(a)
        self.allocations = alloc
        self.pay_by_period: dict[tuple[str, str], list[Payment]] = defaultdict(list)
        self.unallocated_by_ref: dict[str, list[Payment]] = defaultdict(list)
        by_reference: dict[str, list[Payment]] = defaultdict(list)
        for p in all_payments:
            by_reference[p.payment_reference].append(p)
        for p in self.payments:
            if p.allocation_status == "allocated" and p.employer_ref and p.period_code:
                self.pay_by_period[(p.employer_ref, p.period_code)].append(p)
            elif p.employer_ref and p.employer_id is not None and p.reversal_status != "reversed":
                self.unallocated_by_ref[p.employer_ref].append(p)
        self.payment_conflicts: set[tuple[str, str]] = set()
        for _ref, group in by_reference.items():
            if len({p.natural_key.split("|", 1)[0] for p in group}) < 2:
                continue
            shapes = {(p.amount, p.employer_ref, p.period_code) for p in group}
            if len(shapes) > 1:
                for p in group:
                    if p.employer_ref and p.period_code:
                        self.payment_conflicts.add((p.employer_ref, p.period_code))
        self.assessments = list(db.execute(select(Assessment).where(Assessment.is_current)).scalars())
        self.coverage = {
            (c.feed_type, c.period_code, c.scope_lga): c
            for c in db.execute(select(SourceCoverage).where(SourceCoverage.is_current)).scalars()
        }
        batches = list(
            db.execute(
                select(IngestBatch).where(
                    IngestBatch.qa_status == "committed", IngestBatch.extracted_at <= as_of
                )
            ).scalars()
        )
        self.batch_ids = sorted(str(b.id) for b in batches)
        self.latest_extract: dict[str, datetime] = {}
        for b in batches:
            if b.feed_type not in self.latest_extract or b.extracted_at > self.latest_extract[b.feed_type]:
                self.latest_extract[b.feed_type] = b.extracted_at
        self.sla = min([s.freshness_sla_days for s in db.execute(select(DataSource)).scalars()] or [7])
        self.quarantined = list(
            db.execute(select(SourceRecord).where(SourceRecord.status == "quarantined")).scalars()
        )
        self.batch_coverage = {
            b.id: (b.coverage_from, b.coverage_to) for b in db.execute(select(IngestBatch)).scalars()
        }
        self.quarantine_periods: dict[str, set[str]] = defaultdict(set)
        for r in self.quarantined:
            if r.resolution in ACTIVE_QUARANTINE and "invalid_period" in r.reason_codes and r.employer_ref:
                cf, ct = self.batch_coverage.get(r.batch_id, (None, None))
                window = legal.period_range(cf, ct) if cf and ct else periods
                self.quarantine_periods[r.employer_ref].update(window)
        self.disputed: set[tuple[str, str | None]] = set()
        self.legal_holds: set[tuple[str, str | None]] = set()
        for rf in db.execute(
            select(RiskFinding).where(RiskFinding.status.in_(OPEN_FINDING_STATES))
        ).scalars():
            if rf.disputed:
                self.disputed.add((rf.subject_id, rf.period_code))
            if "officer_legal_hold" in rf.holds:  # set by a legal approver, not derived from source data
                self.legal_holds.add((rf.subject_id, rf.period_code))
        anchor = None
        for period in periods:
            sched = self.schedules.get((RETURN_CODE, period))
            if sched is not None and sched.due_at < as_of:
                anchor = period
        self.anchor = anchor

    def staleness(self, feeds: list[str]) -> int | None:
        ages = []
        for feed in feeds:
            ts = self.latest_extract.get(feed)
            if ts is None:
                return None
            ages.append((self.as_of - ts).days)
        return max(ages) if ages else None

    def covered(self, feed: str, period: str, lga: str | None) -> bool:
        c = self.coverage.get((feed, period, None)) or (
            self.coverage.get((feed, period, lga)) if lga else None
        )
        return bool(c and c.complete and c.reconciled)

    def identity_quality(self, ref: str) -> tuple[bool, float, list[str]]:
        emp = self.employers.get(ref)
        m = self.matches.get(ref)
        if emp is None or m is None:
            return False, 0.0, []
        verified = m.status in ("auto_linked", "confirmed") and emp.taxpayer_id is not None
        refs = [f"identity:{m.id}"]
        return verified, float(m.confidence if verified else min(m.confidence, 0.5)), refs


def _obligation_status(ctx: FactsContext, emp: Employer, period: str) -> tuple[str, list[str]]:
    start, end = legal.period_bounds(period)
    obls = [o for o in ctx.obligations.get(emp.source_employer_id, []) if o.tax_type == "PAYE"]
    refs: list[str] = []
    if emp.activity_to is not None and emp.activity_to < start:
        return "ceased", [f"src:employer:{emp.source_employer_id}"]
    covering = [
        o for o in obls if o.effective_from <= end and (o.effective_to is None or o.effective_to >= start)
    ]
    if not covering:
        ended = [o for o in obls if o.effective_to is not None and o.effective_to < start]
        if ended:
            return "ceased", [f"src:obligation:{o.natural_key}" for o in ended]
        return "none", refs
    o = max(covering, key=lambda x: x.effective_from)
    refs.append(f"src:obligation:{o.natural_key}")
    status = o.status
    if status == "active" and (
        (RETURN_CODE, period) not in ctx.schedules or (REMIT_CODE, period) not in ctx.schedules
    ):
        status = "pending_verification"
    if status == "active" and o.exemption_status == "exempt":
        status = "ceased"
    return status, refs


def _employer_period(ctx: FactsContext, emp: Employer, period: str) -> FactRecord:
    ref = emp.source_employer_id
    as_of = ctx.as_of
    start, _ = legal.period_bounds(period)
    status, obligation_refs = _obligation_status(ctx, emp, period)
    ev: dict[str, list[str]] = {"_subject": [f"src:employer:{ref}"], "_obligation": obligation_refs}
    legal_versions: dict[str, dict[str, str]] = {}

    def schedule(code: str, ext_type: str) -> tuple[datetime | None, bool, bool, list[str]]:
        s = ctx.schedules.get((code, period))
        refs: list[str] = []
        if s is None:
            return None, False, False, refs
        v = ctx.legal_versions[s.legal_rule_version_id]
        legal_versions[code] = {"id": str(v.id), "label": f"{v.code}@{v.version}"}
        refs.append(f"legal:{v.code}@{v.version}")
        due = s.due_at
        x = ctx.extensions.get((ref, ext_type, period))
        active = pending = False
        if x is not None and x.status == "approved" and x.new_due_at > due:
            due, active = x.new_due_at, True
            refs.append(f"src:extension:{x.natural_key}")
        elif x is not None and x.status == "pending":
            pending = True
            refs.append(f"src:extension:{x.natural_key}")
        return due, active, pending, refs

    return_due, ext_active, ext_pending, return_refs = schedule(RETURN_CODE, "paye_return")
    pay_due, pay_ext_active, pay_ext_pending, pay_refs = schedule(REMIT_CODE, "paye_remittance")
    ev["return_due_at"] = return_refs
    ev["payment_due_at"] = pay_refs

    filings = ctx.filings.get((ref, period), [])
    sor_filings = [f for f in filings if f.source_name in ctx.sor_sources]
    accepted = [
        f
        for f in sor_filings
        if f.status in ("accepted", "corrected") and f.accepted_at is not None and f.accepted_at <= as_of
    ]
    accepted_at = min((f.accepted_at for f in accepted), default=None)  # type: ignore[type-var]
    pending = [
        f
        for f in sor_filings
        if f.status == "submitted" and f.submitted_at is not None and f.submitted_at <= as_of
    ]
    processing_open = (
        bool(pending)
        and not accepted
        and any(
            (return_due is not None and f.submitted_at <= return_due)  # type: ignore[operator]
            or (as_of - f.submitted_at).days <= ctx.processing_window_days  # type: ignore[operator]
            for f in pending
        )
    )
    latest = max(
        sor_filings,
        key=lambda f: f.submitted_at or f.accepted_at or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    rejected_uncorrected = bool(latest and latest.status == "rejected" and not accepted)
    sources_status = defaultdict(set)
    for f in filings:
        sources_status[f.source_name].add(f.status)
    statuses = set().union(*sources_status.values()) if sources_status else set()
    filing_conflict = (
        len(sources_status) > 1 and "accepted" in statuses and bool(statuses & {"rejected", "not_received"})
    )
    source_conflict = filing_conflict or (ref, period) in ctx.payment_conflicts
    declared = None
    if accepted:
        latest_accepted = max(accepted, key=lambda f: f.accepted_at)  # type: ignore[arg-type,return-value]
        declared = latest_accepted.amount_declared
    ev["accepted_filing_count"] = [f"src:filing:{f.filing_reference}" for f in filings] or [
        f"coverage:ngsirs_paye_return:{period}"
    ]
    ev["filing_late_days"] = [f"src:filing:{f.filing_reference}" for f in accepted]
    ev["declared_payable"] = [f"src:filing:{f.filing_reference}" for f in accepted]

    pays = ctx.pay_by_period.get((ref, period), [])
    settled = [p for p in pays if p.settlement_status == "settled" and p.reversal_status != "reversed"]
    reversed_ = [p for p in pays if p.reversal_status == "reversed"]
    paid_total = sum((p.amount for p in settled), Decimal("0"))
    credits = sum((p.credit_adjustment for p in pays if p.reversal_status != "reversed"), Decimal("0"))
    first_paid = min((p.paid_at for p in settled), default=None)
    unallocated = [
        p
        for p in ctx.unallocated_by_ref.get(ref, [])
        if p.period_code == period or (p.period_code is None and p.paid_at.date() >= start)
    ]
    residual = None
    if declared is not None:
        residual = float((declared - paid_total - credits).quantize(Decimal("0.01")))
    ev["settled_payment_count"] = [f"src:payment:{p.payment_reference}" for p in pays] or [
        f"coverage:ngsirs_payment:{period}"
    ]
    ev["payment_late_days"] = [f"src:payment:{p.payment_reference}" for p in settled]
    ev["residual_amount"] = ev["declared_payable"] + [f"src:payment:{p.payment_reference}" for p in pays]
    ev["possible_unallocated_receipt"] = [f"src:payment:{p.payment_reference}" for p in unallocated]
    ev["source_conflict"] = [f"src:filing:{f.filing_reference}" for f in filings]

    verified, confidence, id_refs = ctx.identity_quality(ref)
    ev["_subject"] += id_refs
    lga = emp.lga_code
    assessment_hold = any(
        a.employer_ref == ref and a.period_code == period and a.appeal_status in ("appealed", "stayed")
        for a in ctx.assessments
    )
    facts: dict[str, Any] = {
        "anchor_period": period == ctx.anchor,
        "obligation_status": status,
        "return_due_at": _iso(return_due),
        "payment_due_at": _iso(pay_due),
        "return_due_passed": bool(return_due and as_of > return_due),
        "payment_due_passed": bool(pay_due and as_of > pay_due),
        "extension_active": ext_active or pay_ext_active,
        "extension_pending": ext_pending or pay_ext_pending,
        "accepted_filing_count": len({f.filing_reference for f in accepted}),
        "accepted_at": _iso(accepted_at),
        "filing_late_days": _days_late(accepted_at, return_due),
        "submission_pending": bool(pending) and not accepted,
        "processing_window_open": processing_open,
        "rejected_uncorrected": rejected_uncorrected,
        "declared_payable": _money(declared),
        "paid_allocated_total": float(paid_total),
        "credits_adjustments_total": float(credits),
        "residual_amount": residual,
        "settled_payment_count": len(settled),
        "first_payment_at": _iso(first_paid),
        "payment_late_days": _days_late(first_paid, pay_due),
        "reversed_payment_count": len(reversed_),
        "reversal_pending": any(p.reversal_status == "reversal_pending" for p in pays),
        "possible_unallocated_receipt": bool(unallocated),
        "bank_delay_dispute": any(p.bank_delay_dispute for p in pays),
        "quarantined_period_records": period in ctx.quarantine_periods.get(ref, set()),
        "source_conflict": source_conflict,
        "legal_hold": assessment_hold or (ref, period) in ctx.legal_holds,
        "disputed": (ref, period) in ctx.disputed,
    }
    quality = {
        "identity_verified": verified,
        "match_confidence": confidence,
        "staleness_days": ctx.staleness(EMPLOYER_FEEDS),
        "freshness_sla_days": ctx.sla,
        "coverage": {
            "filing": ctx.covered("ngsirs_paye_return", period, lga),
            "payment": ctx.covered("ngsirs_payment", period, lga),
        },
    }
    return {
        "kind": "employer_period",
        "subject_type": "employer",
        "subject_id": ref,
        "period": period,
        "tax_type": "PAYE",
        "facts": facts,
        "quality": quality,
        "evidence": ev,
        "legal_versions": legal_versions,
        "lga_code": lga,
    }


def _history(records: list[FactRecord]) -> None:
    """Attach per-series history (oldest -> current) used by repeat-pattern rules."""
    hist_f: list[dict[str, Any]] = []
    hist_p: list[dict[str, Any]] = []
    for r in records:
        f, q = r["facts"], r["quality"]
        active = f["obligation_status"] == "active"
        cov = q["coverage"]
        f_elig = (
            active
            and f["return_due_passed"]
            and cov["filing"]
            and not (f["processing_window_open"] or f["source_conflict"] or f["quarantined_period_records"])
        )
        p_elig = (
            active
            and f["payment_due_passed"]
            and cov["payment"]
            and not (
                f["possible_unallocated_receipt"]
                or f["source_conflict"]
                or f["quarantined_period_records"]
                or f["bank_delay_dispute"]
            )
        )
        hist_f.append(
            {
                "period": r["period"],
                "eligible": bool(f_elig),
                "missing": bool(f_elig and f["accepted_filing_count"] == 0),
                "late": bool(active and cov["filing"] and (f["filing_late_days"] or 0) > 0),
            }
        )
        hist_p.append(
            {
                "period": r["period"],
                "eligible": bool(p_elig),
                "missing": bool(p_elig and f["settled_payment_count"] == 0),
                "late": bool(
                    active
                    and cov["payment"]
                    and not f["bank_delay_dispute"]
                    and (f["payment_late_days"] or 0) > 0
                ),
            }
        )
        r["history"] = {"filing": list(hist_f), "payment": list(hist_p)}


def _assessment_records(ctx: FactsContext) -> list[FactRecord]:
    out: list[FactRecord] = []
    for a in ctx.assessments:
        if a.period_code not in ctx.periods:
            continue
        served = a.status == "served" and a.served_on is not None and a.served_on <= ctx.as_of.date()
        due = a.due_date
        legal_versions: dict[str, dict[str, str]] = {}
        v = legal.resolve(ctx.db, ASSESS_CODE, a.period_code)
        if v is not None:
            legal_versions[ASSESS_CODE] = {"id": str(v.id), "label": f"{v.code}@{v.version}"}
            if due is None and a.served_on is not None:
                due = a.served_on + timedelta(days=int(v.parameters["payment_days_after_service"]))
        verified, confidence, id_refs = ctx.identity_quality(a.employer_ref)
        emp = ctx.employers.get(a.employer_ref)
        lga = emp.lga_code if emp else None
        due_passed = bool(due and legal.end_of_day_wat(due) < ctx.as_of)
        out.append(
            {
                "kind": "assessment",
                "subject_type": "assessment",
                "subject_id": a.assessment_ref,
                "period": a.period_code,
                "tax_type": "PAYE",
                "facts": {
                    "assessment_status": a.status,
                    "served": served,
                    "due_date": _iso(due),
                    "due_passed": due_passed,
                    "appeal_status": a.appeal_status,
                    "outstanding_amount": float(a.outstanding_amount),
                    "assessed_amount": float(a.amount),
                    "employer_ref": a.employer_ref,
                    "legal_hold": a.appeal_status in ("appealed", "stayed")
                    or (a.assessment_ref, a.period_code) in ctx.legal_holds,
                    "disputed": (a.assessment_ref, a.period_code) in ctx.disputed,
                },
                "quality": {
                    "identity_verified": verified,
                    "match_confidence": confidence,
                    "staleness_days": ctx.staleness(["ngsirs_employer", "ngsirs_assessment"]),
                    "freshness_sla_days": ctx.sla,
                    "coverage": {"assessment": ctx.covered("ngsirs_assessment", a.period_code, lga)},
                },
                "evidence": {
                    "_subject": [
                        f"src:assessment:{a.assessment_ref}",
                        f"src:employer:{a.employer_ref}",
                        *id_refs,
                    ],
                    "outstanding_amount": [f"src:assessment:{a.assessment_ref}"],
                },
                "legal_versions": legal_versions,
                "lga_code": lga,
                "employer_ref": a.employer_ref,
            }
        )
    return out


def _taxpayer_pairs(ctx: FactsContext) -> list[FactRecord]:
    taxpayers = list(ctx.db.execute(select(Taxpayer).where(Taxpayer.is_current)).scalars())
    tokens: dict[uuid.UUID, set[str]] = defaultdict(set)
    for i in ctx.db.execute(select(TaxpayerIdentifier).where(TaxpayerIdentifier.is_current)).scalars():
        tokens[i.taxpayer_id].add(i.token)
    by_token: dict[str, list[Taxpayer]] = defaultdict(list)
    for t in taxpayers:
        for tok in tokens.get(t.id, ()):
            by_token[tok].append(t)
    pairs: dict[tuple[str, str], tuple[Taxpayer, Taxpayer]] = {}
    for group in by_token.values():
        for n, a in enumerate(group):
            for b in group[n + 1 :]:
                ra, rb = sorted((a.source_taxpayer_id, b.source_taxpayer_id))
                pairs[(ra, rb)] = (a, b)
    by_lga: dict[str | None, list[Taxpayer]] = defaultdict(list)
    for t in taxpayers:
        by_lga[t.lga_code].append(t)
    for group in by_lga.values():
        for n, a in enumerate(group):
            for b in group[n + 1 :]:
                if identity.similarity(a.display_name, b.display_name) >= 0.85:
                    ra, rb = sorted((a.source_taxpayer_id, b.source_taxpayer_id))
                    pairs[(ra, rb)] = (a, b)
    out: list[FactRecord] = []
    for (ra, rb), (a, b) in sorted(pairs.items()):
        out.append(
            {
                "kind": "taxpayer_pair",
                "subject_type": "taxpayer_pair",
                "subject_id": f"{ra}~{rb}",
                "period": None,
                "tax_type": "PAYE",
                "facts": {
                    "shared_identifier_count": len(tokens.get(a.id, set()) & tokens.get(b.id, set())),
                    "name_similarity": identity.similarity(a.display_name, b.display_name),
                    "same_lga": a.lga_code == b.lga_code,
                },
                "quality": {
                    "identity_verified": True,
                    "match_confidence": 1.0,
                    "staleness_days": ctx.staleness(["ngsirs_taxpayer"]),
                    "freshness_sla_days": 30,
                    "coverage": {},
                },
                "evidence": {
                    "_subject": [f"src:taxpayer:{ra}", f"src:taxpayer:{rb}"],
                    "shared_identifier_count": [f"src:taxpayer:{ra}", f"src:taxpayer:{rb}"],
                },
                "legal_versions": {},
                "lga_code": a.lga_code,
            }
        )
    return out


def _quarantine_records(ctx: FactsContext) -> list[FactRecord]:
    out: list[FactRecord] = []
    seqs = {b.id: b.seq for b in ctx.db.execute(select(IngestBatch)).scalars()}
    for r in ctx.quarantined:
        if r.resolution not in ACTIVE_QUARANTINE or "invalid_period" not in r.reason_codes:
            continue
        subject = (
            f"{r.feed_type}:{r.natural_id}"
            if r.natural_id
            else f"{r.feed_type}:b{seqs.get(r.batch_id)}r{r.row_number}"
        )
        emp = ctx.employers.get(r.employer_ref or "")
        out.append(
            {
                "kind": "quarantined_record",
                "subject_type": "source_record",
                "subject_id": subject,
                "period": None,
                "tax_type": "PAYE",
                "facts": {
                    "feed_type": r.feed_type,
                    "reason_code": "invalid_period",
                    "employer_known": emp is not None,
                },
                "quality": {
                    "identity_verified": True,
                    "match_confidence": 1.0,
                    "staleness_days": 0,
                    "freshness_sla_days": 30,
                    "coverage": {},
                },
                "evidence": {"_subject": [f"record:{r.id}"], "reason_code": [f"record:{r.id}"]},
                "legal_versions": {},
                "lga_code": emp.lga_code if emp else None,
                "employer_ref": r.employer_ref,
            }
        )
    return out


def _receipts(ctx: FactsContext) -> list[FactRecord]:
    out: list[FactRecord] = []
    for p in ctx.payments:
        if p.allocation_status not in ("unallocated", "suspense") or p.reversal_status == "reversed":
            continue
        emp = ctx.employers.get(p.employer_ref or "")
        out.append(
            {
                "kind": "payment_receipt",
                "subject_type": "payment",
                "subject_id": p.payment_reference,
                "period": None,
                "tax_type": p.tax_type,
                "facts": {
                    "allocation_status": p.allocation_status,
                    "employer_matched": p.employer_id is not None,
                    "amount": float(p.amount),
                    "age_days": (ctx.as_of - p.paid_at).days,
                },
                "quality": {
                    "identity_verified": True,
                    "match_confidence": 1.0,
                    "staleness_days": ctx.staleness(["ngsirs_payment"]),
                    "freshness_sla_days": ctx.sla,
                    "coverage": {},
                },
                "evidence": {
                    "_subject": [f"src:payment:{p.payment_reference}"],
                    "allocation_status": [f"src:payment:{p.payment_reference}"],
                },
                "legal_versions": {},
                "lga_code": emp.lga_code if emp else None,
                "employer_ref": p.employer_ref,
            }
        )
    return out


def build(
    db: Session, tenant: Tenant, as_of: datetime, period_from: str, period_to: str
) -> tuple[list[FactRecord], list[str]]:
    periods = legal.period_range(period_from, period_to)
    ctx = FactsContext(db, tenant, as_of, periods)
    records: list[FactRecord] = []
    for ref in sorted(ctx.employers):
        emp = ctx.employers[ref]
        series = [_employer_period(ctx, emp, p) for p in periods]
        _history(series)
        records.extend(series)
    records.extend(_assessment_records(ctx))
    records.extend(_taxpayer_pairs(ctx))
    records.extend(_quarantine_records(ctx))
    records.extend(_receipts(ctx))
    return records, ctx.batch_ids
