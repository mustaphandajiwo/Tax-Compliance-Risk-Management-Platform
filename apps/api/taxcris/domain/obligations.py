"""Versioned legal catalogue and obligation engine (FR-03, PRD §15).

Legal obligations are declarative ``LegalRule`` rows. For a given period the engine selects the
*approved* rule version whose validity window contains the period start, so historical periods are
always evaluated against the law in force at the time. Rules execute deterministically.

Deadline specification (``LegalRule.deadline``):
  {"type": "days_after_period_end", "days": N}
  {"type": "fixed_date_following_year", "month": M, "day": D}   # annual returns
"""

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..models import LegalRule, Payment, Taxpayer, TaxObligation, TaxReturn, Tenant


class FourEyesViolation(Exception):
    pass


# --------------------------------------------------------------------------------------------
# Legal rule lifecycle: draft → pending_approval → approved (→ retired). Two-person approval.
# --------------------------------------------------------------------------------------------


def submit_rule(db: Session, rule: LegalRule, user_id: uuid.UUID, role: str) -> LegalRule:
    if rule.status != "draft":
        raise ValueError(f"Only draft rules can be submitted (status={rule.status})")
    rule.status, rule.submitted_by = "pending_approval", user_id
    audit.record(db, tenant_id=rule.tenant_id, actor_id=user_id, actor_role=role, action="legal_rule.submitted",
                 resource_type="legal_rule", resource_id=rule.id, details={"rule_code": rule.rule_code, "version": rule.version})
    return rule


def approve_rule(db: Session, rule: LegalRule, user_id: uuid.UUID, role: str, reason: str) -> LegalRule:
    if rule.status != "pending_approval":
        raise ValueError(f"Only pending rules can be approved (status={rule.status})")
    if user_id in (rule.created_by, rule.submitted_by):
        raise FourEyesViolation("Legal rules require approval by a second officer who did not draft or submit them")
    overlapping = db.execute(
        select(LegalRule).where(
            LegalRule.tenant_id == rule.tenant_id,
            LegalRule.rule_code == rule.rule_code,
            LegalRule.status == "approved",
            LegalRule.id != rule.id,
        )
    ).scalars().all()
    for other in overlapping:
        # Close the earlier version's window where the new one starts (versioned supersession).
        if other.valid_from < rule.valid_from and (other.valid_to is None or other.valid_to >= rule.valid_from):
            other.valid_to = rule.valid_from - timedelta(days=1)
        elif other.valid_from >= rule.valid_from and (rule.valid_to is None or other.valid_from <= rule.valid_to):
            raise ValueError(f"Validity window overlaps approved version {other.version}")
    rule.status, rule.approved_by, rule.approved_at = "approved", user_id, datetime.now(timezone.utc)
    audit.record(db, tenant_id=rule.tenant_id, actor_id=user_id, actor_role=role, action="legal_rule.approved",
                 resource_type="legal_rule", resource_id=rule.id,
                 details={"rule_code": rule.rule_code, "version": rule.version, "reason": reason})
    return rule


def retire_rule(db: Session, rule: LegalRule, user_id: uuid.UUID, role: str, reason: str) -> LegalRule:
    """Rollback path: retire a version so the previous approved version applies again."""
    if rule.status != "approved":
        raise ValueError("Only approved rules can be retired")
    rule.status = "retired"
    prev = db.execute(
        select(LegalRule).where(
            LegalRule.tenant_id == rule.tenant_id, LegalRule.rule_code == rule.rule_code,
            LegalRule.status == "approved", LegalRule.valid_to == rule.valid_from - timedelta(days=1),
        )
    ).scalar_one_or_none()
    if prev is not None:
        prev.valid_to = rule.valid_to
    audit.record(db, tenant_id=rule.tenant_id, actor_id=user_id, actor_role=role, action="legal_rule.retired",
                 resource_type="legal_rule", resource_id=rule.id,
                 details={"rule_code": rule.rule_code, "version": rule.version, "reason": reason,
                          "reinstated_version": prev.version if prev else None})
    return rule


def select_rule(rules: list[LegalRule], tax_type: str, on: date) -> LegalRule | None:
    for r in rules:
        if r.tax_type == tax_type and r.status == "approved" and r.valid_from <= on and (r.valid_to is None or on <= r.valid_to):
            return r
    return None


def approved_rules(db: Session, tenant_id: uuid.UUID) -> list[LegalRule]:
    return list(
        db.execute(
            select(LegalRule).where(LegalRule.tenant_id == tenant_id, LegalRule.status == "approved").order_by(LegalRule.version.desc())
        ).scalars()
    )


# --------------------------------------------------------------------------------------------
# Periods and deadlines
# --------------------------------------------------------------------------------------------


def period_bounds(period: str) -> tuple[date, date]:
    if len(period) == 4:
        y = int(period)
        return date(y, 1, 1), date(y, 12, 31)
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def periods_for(frequency: str, scope: str) -> list[str]:
    """Expand a run scope ('2026' or '2026-03') into the rule's period units."""
    if frequency == "annual":
        return [scope[:4]]
    if len(scope) == 7:
        return [scope]
    return [f"{scope}-{m:02d}" for m in range(1, 13)]


def compute_due_date(deadline: dict, period_end: date) -> date:
    kind = deadline["type"]
    if kind == "days_after_period_end":
        return period_end + timedelta(days=int(deadline["days"]))
    if kind == "fixed_date_following_year":
        return date(period_end.year + 1, int(deadline["month"]), int(deadline["day"]))
    raise ValueError(f"Unknown deadline type {kind}")


def is_eligible(rule: LegalRule, tp: Taxpayer, period_start: date, period_end: date, jurisdiction: str) -> bool:
    if tp.merged_into_id is not None or tp.deleted_at is not None:
        return False
    # Unregistered entities surface as registration signals; an obligation is only asserted once
    # identity and liability are verified through registration.
    if tp.registration_status != "registered" or tp.tax_residence != jurisdiction:
        return False
    for field, expected in (rule.eligibility or {}).items():
        if getattr(tp, field, None) != expected:
            return False
    # No obligation for periods starting after closure. A dormant business still has obligations.
    if tp.closed_on is not None and tp.closed_on < period_start:
        return False
    if tp.registered_on is not None and tp.registered_on > period_end:
        return False
    return True


def generate(db: Session, tenant_id: uuid.UUID, tax_type: str, scope: str, as_of: date) -> dict:
    """Create/refresh obligations for a scope and link returns/payments. Idempotent."""
    rules = approved_rules(db, tenant_id)
    jurisdiction = db.get(Tenant, tenant_id).state_code
    taxpayers = list(
        db.execute(
            select(Taxpayer).where(Taxpayer.tenant_id == tenant_id, Taxpayer.merged_into_id.is_(None), Taxpayer.deleted_at.is_(None))
        ).scalars()
    )
    existing = {
        (o.taxpayer_id, o.period): o
        for o in db.execute(
            select(TaxObligation).where(TaxObligation.tenant_id == tenant_id, TaxObligation.tax_type == tax_type)
        ).scalars()
    }
    any_rule = next((r for r in rules if r.tax_type == tax_type), None)
    if any_rule is None:
        return {"created": 0, "updated": 0, "rule_versions": {}}
    created = updated = 0
    versions: dict[str, int] = {}
    for period in periods_for(any_rule.frequency, scope):
        start, end = period_bounds(period)
        rule = select_rule(rules, tax_type, start)
        if rule is None:
            continue
        versions[period] = rule.version
        due = compute_due_date(rule.deadline, end)
        for tp in taxpayers:
            if not is_eligible(rule, tp, start, end, jurisdiction):
                continue
            ob = existing.get((tp.id, period))
            if ob is None:
                ob = TaxObligation(
                    tenant_id=tenant_id, taxpayer_id=tp.id, tax_type=tax_type, period=period, period_start=start,
                    period_end=end, due_date=due, legal_rule_id=rule.id, rule_version=rule.version,
                )
                db.add(ob)
                existing[(tp.id, period)] = ob
                created += 1
            elif ob.legal_rule_id != rule.id or ob.due_date != due:
                ob.legal_rule_id, ob.rule_version, ob.due_date = rule.id, rule.version, due
                updated += 1
    db.flush()
    _link_and_status(db, tenant_id, tax_type, scope, as_of)
    return {"created": created, "updated": updated, "rule_versions": versions}


def _in_scope(period: str, scope: str) -> bool:
    return period == scope or period.startswith(scope + "-") or (len(period) == 4 and scope.startswith(period))


def _link_and_status(db: Session, tenant_id: uuid.UUID, tax_type: str, scope: str, as_of: date) -> None:
    obligations = {
        (o.taxpayer_id, o.period): o
        for o in db.execute(
            select(TaxObligation).where(TaxObligation.tenant_id == tenant_id, TaxObligation.tax_type == tax_type)
        ).scalars()
        if _in_scope(o.period, scope)
    }
    returns_by_ob: dict[uuid.UUID, list[TaxReturn]] = {}
    for r in db.execute(select(TaxReturn).where(TaxReturn.tenant_id == tenant_id, TaxReturn.tax_type == tax_type)).scalars():
        ob = obligations.get((r.taxpayer_id, r.period))
        if ob is not None:
            r.obligation_id = ob.id
            returns_by_ob.setdefault(ob.id, []).append(r)
    for p in db.execute(select(Payment).where(Payment.tenant_id == tenant_id, Payment.tax_type == tax_type)).scalars():
        if p.period:
            ob = obligations.get((p.taxpayer_id, p.period))
            if ob is not None:
                p.obligation_id = ob.id
    for ob in obligations.values():
        if ob.status == "exempt":
            continue
        deadline = ob.extension_until or ob.due_date
        rets = returns_by_ob.get(ob.id, [])
        if rets:
            first = min(r.filing_date for r in rets)
            ob.status = "filed" if first <= deadline else "filed_late"
        else:
            ob.status = "overdue" if as_of > deadline else "open"
    db.flush()


def declared_liability(returns: list[TaxReturn]) -> Decimal:
    """Latest filed return wins (amended returns supersede)."""
    if not returns:
        return Decimal("0")
    return max(returns, key=lambda r: (r.filing_date, r.created_at)).reported_amount
