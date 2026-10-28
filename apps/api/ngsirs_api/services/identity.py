"""Entity resolution: deterministic first, reviewed probabilistic second (FR-005/006).

Probabilistic matches only auto-link above a threshold that NGSIRS has
approved (tenant setting ``identity.probabilistic_threshold`` with an
``approved_by``). Below it, or with no approved threshold, the match waits in
the data-steward review queue and every rule treats the employer's identity as
unverified (hold, never adverse action). Links are reversible; retracting one
flags every dependent finding.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.states import OPEN_FINDING_STATES

from .. import audit
from ..errors import conflict, not_found
from ..models import CaseRecord, Employer, FindingEvent, IdentityMatch, RiskFinding, Taxpayer, Tenant
from ..security.auth import Principal

STOPWORDS = {"ltd", "limited", "plc", "nig", "nigeria", "enterprises", "and", "the", "co", "company"}


def normalise_name(name: str) -> str:
    tokens = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in STOPWORDS]
    return " ".join(sorted(tokens))


def similarity(a: str, b: str) -> float:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:
        return 0.0
    return round(SequenceMatcher(None, na, nb).ratio(), 4)


def threshold(tenant: Tenant) -> float | None:
    cfg = (tenant.settings or {}).get("identity", {})
    if not cfg.get("approved_by"):
        return None
    return float(cfg.get("probabilistic_threshold", 0.98))


def resolve_employer(
    db: Session,
    tenant: Tenant,
    employer: Employer,
    by_ref: dict[str, Taxpayer],
    by_lga: dict[str | None, list[Taxpayer]],
    source_record_id: uuid.UUID,
    prior: dict[str, IdentityMatch],
) -> IdentityMatch:
    previous = prior.get(employer.source_employer_id)
    if previous is not None and previous.status == "confirmed" and previous.taxpayer_id is not None:
        employer.taxpayer_id = previous.taxpayer_id
        match = IdentityMatch(
            tenant_id=tenant.id,
            employer_id=employer.id,
            source_record_id=source_record_id,
            taxpayer_id=previous.taxpayer_id,
            match_type="manual",
            confidence=1.0,
            status="confirmed",
            reviewer=previous.reviewer,
            reviewed_at=previous.reviewed_at,
            method_detail={
                "rule": "carried_forward_confirmation",
                "employer_ref": employer.source_employer_id,
                "previous_match_id": str(previous.id),
            },
        )
        db.add(match)
        return match

    detail: dict[str, Any] = {"employer_ref": employer.source_employer_id}
    tp = by_ref.get(employer.linked_taxpayer_ref or "")
    if tp is not None:
        employer.taxpayer_id = tp.id
        detail.update(rule="exact_source_taxpayer_id", taxpayer_ref=tp.source_taxpayer_id)
        match = IdentityMatch(
            tenant_id=tenant.id,
            employer_id=employer.id,
            source_record_id=source_record_id,
            taxpayer_id=tp.id,
            match_type="deterministic",
            confidence=1.0,
            status="auto_linked",
            method_detail=detail,
        )
        db.add(match)
        return match

    candidates = by_lga.get(employer.lga_code, [])
    best: tuple[float, Taxpayer | None] = (0.0, None)
    for c in candidates:
        s = similarity(employer.display_name, c.display_name)
        if s > best[0]:
            best = (s, c)
    score, cand = best
    limit = threshold(tenant)
    detail.update(
        rule="name_similarity_same_lga",
        score=score,
        threshold=limit,
        linked_ref_supplied=employer.linked_taxpayer_ref,
        candidate_ref=cand.source_taxpayer_id if cand else None,
    )
    if cand is not None and limit is not None and score >= limit:
        employer.taxpayer_id = cand.id
        status = "auto_linked"
    else:
        employer.taxpayer_id = None
        status = "pending_review"
    match = IdentityMatch(
        tenant_id=tenant.id,
        employer_id=employer.id,
        source_record_id=source_record_id,
        taxpayer_id=cand.id if cand else None,
        match_type="probabilistic",
        confidence=score,
        status=status,
        method_detail=detail,
    )
    db.add(match)
    return match


def latest_matches(db: Session) -> dict[str, IdentityMatch]:
    """Most recent identity match per employer reference."""
    out: dict[str, IdentityMatch] = {}
    for m in db.execute(select(IdentityMatch).order_by(IdentityMatch.created_at)).scalars():
        ref = (m.method_detail or {}).get("employer_ref")
        if ref:
            out[ref] = m
    return out


def decide(db: Session, actor: Principal, match_id: uuid.UUID, decision: str, reason: str) -> dict[str, Any]:
    m = db.get(IdentityMatch, match_id)
    if m is None:
        raise not_found("Identity match")
    employer = db.get(Employer, m.employer_id) if m.employer_id else None
    affected: dict[str, Any] = {"findings": [], "cases": []}
    before = {"status": m.status, "taxpayer_id": str(m.taxpayer_id) if m.taxpayer_id else None}
    if decision == "confirm":
        if m.status != "pending_review" or m.taxpayer_id is None:
            raise conflict("Only pending matches with a candidate can be confirmed")
        m.status = "confirmed"
        if employer is not None:
            employer.taxpayer_id = m.taxpayer_id
    elif decision == "reject":
        if m.status != "pending_review":
            raise conflict("Only pending matches can be rejected")
        m.status = "rejected"
    elif decision == "retract":
        if m.status not in ("auto_linked", "confirmed"):
            raise conflict("Only linked matches can be retracted")
        m.status = "retracted"
        if employer is not None:
            employer.taxpayer_id = None
            affected = retract_dependents(db, actor, employer, reason)
    else:
        raise conflict(f"Unknown decision {decision}")
    m.reviewer = actor.actor_id
    m.reviewed_at = datetime.now(UTC)
    m.reason = reason
    db.flush()
    audit.record(
        db,
        actor,
        f"identity.{decision}",
        f"identity_match:{m.id}",
        {"reason": reason, "employer_ref": (m.method_detail or {}).get("employer_ref"), **affected},
        before=before,
        after={"status": m.status},
    )
    return {"match_id": str(m.id), "status": m.status, **affected}


def retract_dependents(db: Session, actor: Principal, employer: Employer, reason: str) -> dict[str, Any]:
    """Every open finding and case that relied on the retracted link is held for data review."""
    ref = employer.source_employer_id
    employer_ids = [
        e.id for e in db.execute(select(Employer).where(Employer.source_employer_id == ref)).scalars()
    ]
    findings = list(
        db.execute(
            select(RiskFinding).where(
                RiskFinding.employer_id.in_(employer_ids), RiskFinding.status.in_(OPEN_FINDING_STATES)
            )
        ).scalars()
    )
    case_refs: list[str] = []
    for f in findings:
        f.data_hold = True
        if "identity_retracted" not in f.holds:
            f.holds = [*f.holds, "identity_retracted"]
        f.allowed_next_action = "data_review"
        f.version += 1
        db.add(
            FindingEvent(
                tenant_id=f.tenant_id,
                finding_id=f.id,
                event_type="identity_retracted",
                actor_id=actor.actor_id,
                reason=reason,
                details={"employer_ref": ref},
            )
        )
        for c in db.execute(
            select(CaseRecord).where(
                CaseRecord.finding_id == f.id, CaseRecord.stage.notin_(["closed", "rejected"])
            )
        ).scalars():
            c.outward_permitted = False
            c.legal_hold = True
            c.version += 1
            case_refs.append(c.case_ref)
    return {"findings": [f.finding_ref for f in findings], "cases": case_refs}
