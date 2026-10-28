"""Legal obligation service: effective-dated statutory versions and due dates.

No rate or deadline is hard-coded. Due dates come from the parameters of the
legal rule version whose effective window contains the period, and only
versions approved by an NGSIRS legal approver count. A period with no approved
version has an *unverified* obligation, which the engine turns into a hold.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from importer.validation import WAT
from risk_engine.hashing import sha256_hex

from .. import audit
from ..errors import conflict, forbidden, not_found, unprocessable
from ..models import LegalInstrument, LegalRuleVersion, PeriodSchedule
from ..security.auth import Principal

# Obligation codes the PAYE pilot uses, with the parameter each must define.
OBLIGATION_CODES: dict[str, dict[str, Any]] = {
    "PAYE_EMPLOYER_MONTHLY_RETURN": {
        "tax_type": "PAYE",
        "obligation_type": "paye_return",
        "required": ["due_day_of_following_month"],
    },
    "PAYE_EMPLOYER_REMITTANCE": {
        "tax_type": "PAYE",
        "obligation_type": "paye_remittance",
        "required": ["due_day_of_following_month"],
    },
    "PAYE_ASSESSMENT": {
        "tax_type": "PAYE",
        "obligation_type": "paye_assessment",
        "required": ["payment_days_after_service"],
    },
}


def period_bounds(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y + (m // 12):04d}-{(m % 12) + 1:02d}"


def period_range(start: str, end: str) -> list[str]:
    out, p = [], start
    while p <= end:
        out.append(p)
        p = next_period(p)
    return out


def end_of_day_wat(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=WAT).astimezone(UTC)


def due_date_for(period: str, params: dict[str, Any]) -> datetime:
    _, end = period_bounds(period)
    following = end + timedelta(days=1)
    day = min(
        int(params["due_day_of_following_month"]), calendar.monthrange(following.year, following.month)[1]
    )
    return end_of_day_wat(following.replace(day=day))


def versions_for(db: Session, code: str) -> list[LegalRuleVersion]:
    return list(
        db.execute(
            select(LegalRuleVersion)
            .where(LegalRuleVersion.code == code)
            .order_by(LegalRuleVersion.effective_from)
        ).scalars()
    )


def resolve(db: Session, code: str, period: str, *, approved_only: bool = True) -> LegalRuleVersion | None:
    """The version in force for the period: the latest effective_from that covers the period start.

    A later version takes precedence from its own effective date, so an open-ended earlier version never has
    to be edited (approved versions are immutable) when the law changes.
    """
    start, _ = period_bounds(period)
    covering = [
        v
        for v in versions_for(db, code)
        if (not approved_only or v.status == "approved")
        and v.effective_from <= start
        and (v.effective_to is None or start <= v.effective_to)
    ]
    return max(covering, key=lambda v: v.effective_from, default=None)


def content_hash(v: dict[str, Any]) -> str:
    return sha256_hex(
        {
            k: v[k]
            for k in (
                "code",
                "version",
                "effective_from",
                "effective_to",
                "parameters",
                "provision_ref",
                "jurisdiction",
            )
        }
    )


def draft_version(db: Session, actor: Principal, data: dict[str, Any]) -> LegalRuleVersion:
    code = data["code"]
    spec = OBLIGATION_CODES.get(code)
    if spec is None:
        raise unprocessable(f"Unknown obligation code {code}", {"known": list(OBLIGATION_CODES)})
    missing = [p for p in spec["required"] if p not in data["parameters"]]
    if missing:
        raise unprocessable("Missing legal parameters", {"missing": missing})
    instrument = db.execute(
        select(LegalInstrument).where(LegalInstrument.code == data["instrument_code"])
    ).scalar_one_or_none()
    if instrument is None:
        raise not_found("Legal instrument")
    eff_from: date = data["effective_from"]
    eff_to: date | None = data.get("effective_to")
    if eff_to is not None and eff_to < eff_from:
        raise unprocessable("effective_to precedes effective_from")
    for other in versions_for(db, code):
        if other.status in ("approved", "pending_approval") and other.effective_from == eff_from:
            raise conflict(
                f"{other.code} {other.version} ({other.status}) already takes effect on {eff_from}"
            )
    row = LegalRuleVersion(
        tenant_id=actor.tenant_id,
        code=code,
        version=data["version"],
        tax_type=spec["tax_type"],
        obligation_type=spec["obligation_type"],
        instrument_id=instrument.id,
        provision_ref=data["provision_ref"],
        jurisdiction=data.get("jurisdiction", "NG-NI"),
        effective_from=eff_from,
        effective_to=eff_to,
        parameters=data["parameters"],
        status="pending_approval",
        drafted_by=actor.actor_id,
        is_synthetic=data.get("is_synthetic", True),
        content_hash="",
    )
    row.content_hash = content_hash(
        {
            "code": code,
            "version": row.version,
            "effective_from": eff_from,
            "effective_to": eff_to,
            "parameters": row.parameters,
            "provision_ref": row.provision_ref,
            "jurisdiction": row.jurisdiction,
        }
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        actor,
        "legal.version_drafted",
        f"legal:{code}@{row.version}",
        {
            "effective_from": str(eff_from),
            "effective_to": str(eff_to) if eff_to else None,
            "parameters": row.parameters,
        },
        after=row.content_hash,
    )
    return row


def approve_version(db: Session, actor: Principal, version_id: uuid.UUID, note: str) -> LegalRuleVersion:
    row = db.get(LegalRuleVersion, version_id)
    if row is None:
        raise not_found("Legal version")
    if row.status != "pending_approval":
        raise conflict(f"Legal version is {row.status}, not pending approval")
    if row.drafted_by == actor.actor_id:
        raise forbidden("Maker-checker: the drafter cannot approve their own legal version")
    row.status = "approved"
    row.approved_by = actor.actor_id
    row.approved_at = datetime.now(UTC)
    row.approval_note = note
    db.flush()
    audit.record(
        db,
        actor,
        "legal.version_approved",
        f"legal:{row.code}@{row.version}",
        {"note": note},
        after=row.content_hash,
    )
    return row


def ensure_schedules(db: Session, tenant_id: uuid.UUID, periods: list[str]) -> int:
    """Materialise due dates for every (obligation code, period) with an approved version."""
    existing = {(s.legal_code, s.period_code): s for s in db.execute(select(PeriodSchedule)).scalars()}
    created = 0
    for code, spec in OBLIGATION_CODES.items():
        if "due_day_of_following_month" not in spec["required"]:
            continue
        for p in periods:
            v = resolve(db, code, p)
            if v is None:
                continue
            due = due_date_for(p, v.parameters)
            current = existing.get((code, p))
            if current is not None:
                if current.legal_rule_version_id != v.id or current.due_at != due:
                    current.legal_rule_version_id = v.id
                    current.due_at = due
                continue
            start, end = period_bounds(p)
            db.add(
                PeriodSchedule(
                    tenant_id=tenant_id,
                    tax_type=spec["tax_type"],
                    obligation_type=spec["obligation_type"],
                    legal_code=code,
                    period_code=p,
                    period_start=start,
                    period_end=end,
                    due_at=due,
                    legal_rule_version_id=v.id,
                )
            )
            created += 1
    db.flush()
    return created
