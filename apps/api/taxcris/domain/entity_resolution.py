"""Entity resolution and four-eyes merges (FR-02).

Candidate generation is deterministic:
* shared hashed TIN / NIN / CAC RC across two live taxpayers  → confidence 0.97
* same type + LGA and normalised-name similarity ≥ 0.88       → confidence = similarity × 0.8

A data steward *proposes* a merge; a different steward *approves* it. Moved rows are recorded on
the candidate so the merge can be rolled back exactly. Businesses and their owners are never
auto-linked: candidates require the same ``taxpayer_type``.
"""

import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import combinations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import audit
from ..models import (
    Alert,
    Case,
    Employment,
    IdentityLink,
    MergeCandidate,
    Payment,
    RiskAssessment,
    Taxpayer,
    TaxObligation,
    TaxReturn,
)

_STOP = {"LTD", "LIMITED", "NIG", "NIGERIA", "ENTERPRISES", "ENT", "VENTURES", "AND", "&", "CO", "COMPANY", "PLC"}


class FourEyesViolation(Exception):
    pass


def normalise_name(name: str) -> str:
    tokens = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    return " ".join(sorted(t for t in tokens if t not in _STOP))


def _live(db: Session, tenant_id: uuid.UUID) -> list[Taxpayer]:
    return list(
        db.execute(
            select(Taxpayer).where(
                Taxpayer.tenant_id == tenant_id, Taxpayer.merged_into_id.is_(None), Taxpayer.deleted_at.is_(None)
            )
        ).scalars()
    )


def find_candidates(db: Session, tenant_id: uuid.UUID) -> int:
    live = {t.id: t for t in _live(db, tenant_id)}
    found: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, list[str]]] = {}

    by_hash: dict[tuple[str, str], set[uuid.UUID]] = {}
    for link in db.execute(select(IdentityLink).where(IdentityLink.tenant_id == tenant_id)).scalars():
        if link.taxpayer_id in live:
            by_hash.setdefault((link.identifier_type, link.hashed_identifier), set()).add(link.taxpayer_id)
    for (id_type, _), ids in by_hash.items():
        for a, b in combinations(sorted(ids, key=lambda i: (live[i].created_at, str(i))), 2):
            if live[a].taxpayer_type != live[b].taxpayer_type:
                continue
            conf, reasons = found.get((a, b), (0.0, []))
            found[(a, b)] = (max(conf, 0.97), reasons + [f"shared_{id_type.lower()}"])

    groups: dict[tuple[str, str | None], list[Taxpayer]] = {}
    for t in live.values():
        groups.setdefault((t.taxpayer_type, t.lga), []).append(t)
    for members in groups.values():
        members.sort(key=lambda t: (t.created_at, str(t.id)))
        norm = {t.id: normalise_name(t.name) for t in members}
        for a, b in combinations(members, 2):
            if not norm[a.id] or not norm[b.id]:
                continue
            sim = SequenceMatcher(None, norm[a.id], norm[b.id]).ratio()
            if sim >= 0.88:
                conf, reasons = found.get((a.id, b.id), (0.0, []))
                found[(a.id, b.id)] = (max(conf, round(sim * 0.8, 3)), reasons + [f"name_similarity:{sim:.2f}", "same_lga"])

    existing = {
        (m.survivor_id, m.duplicate_id)
        for m in db.execute(select(MergeCandidate).where(MergeCandidate.tenant_id == tenant_id)).scalars()
    }
    created = 0
    for (a, b), (conf, reasons) in found.items():
        if (a, b) in existing or (b, a) in existing:
            continue
        db.add(MergeCandidate(tenant_id=tenant_id, survivor_id=a, duplicate_id=b, confidence=conf, reasons=reasons))
        created += 1
    db.flush()
    return created


def propose(db: Session, cand: MergeCandidate, user_id: uuid.UUID, role: str, reason: str) -> MergeCandidate:
    if cand.status != "candidate":
        raise ValueError(f"Cannot propose a merge in status {cand.status}")
    cand.status, cand.proposed_by, cand.decision_reason = "proposed", user_id, reason
    audit.record(
        db, tenant_id=cand.tenant_id, actor_id=user_id, actor_role=role, action="merge.proposed",
        resource_type="merge_candidate", resource_id=cand.id, details={"reason": reason, "confidence": cand.confidence},
    )
    return cand


_MOVABLE = [
    ("identity_links", IdentityLink, "taxpayer_id"),
    ("returns", TaxReturn, "taxpayer_id"),
    ("payments", Payment, "taxpayer_id"),
    ("employments_employer", Employment, "employer_id"),
    ("employments_employee", Employment, "employee_id"),
    ("risk_assessments", RiskAssessment, "taxpayer_id"),
    ("alerts", Alert, "taxpayer_id"),
    ("cases", Case, "taxpayer_id"),
]


def approve(db: Session, cand: MergeCandidate, user_id: uuid.UUID, role: str, reason: str) -> MergeCandidate:
    if cand.status != "proposed":
        raise ValueError(f"Cannot approve a merge in status {cand.status}")
    if cand.proposed_by == user_id:
        raise FourEyesViolation("A merge must be approved by a different data steward than the proposer")
    survivor, dup = db.get(Taxpayer, cand.survivor_id), db.get(Taxpayer, cand.duplicate_id)
    before = {"survivor": str(survivor.id), "duplicate": str(dup.id), "dup_merged_into": None}
    moved: dict[str, list[str]] = {}
    for key, model, col in _MOVABLE:
        ids = [
            str(i)
            for (i,) in db.execute(select(model.id).where(model.tenant_id == cand.tenant_id, getattr(model, col) == dup.id))
        ]
        if ids:
            db.execute(update(model).where(model.id.in_([uuid.UUID(i) for i in ids])).values({col: survivor.id}))
        moved[key] = ids
    # Obligations are regenerated for the survivor; the duplicate's become void.
    obligation_ids = [
        str(i) for (i,) in db.execute(select(TaxObligation.id).where(TaxObligation.taxpayer_id == dup.id))
    ]
    db.execute(update(TaxObligation).where(TaxObligation.taxpayer_id == dup.id).values(status="exempt"))
    db.execute(update(TaxReturn).where(TaxReturn.taxpayer_id == survivor.id).values(obligation_id=None))
    db.execute(update(Payment).where(Payment.taxpayer_id == survivor.id).values(obligation_id=None))
    moved["voided_obligations"] = obligation_ids
    dup.merged_into_id = survivor.id
    cand.status, cand.approved_by, cand.decided_at, cand.moved = "merged", user_id, datetime.now(timezone.utc), moved
    audit.record(
        db, tenant_id=cand.tenant_id, actor_id=user_id, actor_role=role, action="merge.approved",
        resource_type="merge_candidate", resource_id=cand.id,
        details={"reason": reason, "moved_counts": {k: len(v) for k, v in moved.items()}},
        before=before, after={**before, "dup_merged_into": str(survivor.id)},
    )
    return cand


def reject(db: Session, cand: MergeCandidate, user_id: uuid.UUID, role: str, reason: str) -> MergeCandidate:
    if cand.status not in ("candidate", "proposed"):
        raise ValueError(f"Cannot reject a merge in status {cand.status}")
    cand.status, cand.approved_by, cand.decided_at, cand.decision_reason = "rejected", user_id, datetime.now(timezone.utc), reason
    audit.record(
        db, tenant_id=cand.tenant_id, actor_id=user_id, actor_role=role, action="merge.rejected",
        resource_type="merge_candidate", resource_id=cand.id, details={"reason": reason},
    )
    return cand


def rollback(db: Session, cand: MergeCandidate, user_id: uuid.UUID, role: str, reason: str) -> MergeCandidate:
    if cand.status != "merged":
        raise ValueError("Only merged candidates can be rolled back")
    dup = db.get(Taxpayer, cand.duplicate_id)
    for key, model, col in _MOVABLE:
        ids = [uuid.UUID(i) for i in cand.moved.get(key, [])]
        if ids:
            db.execute(update(model).where(model.id.in_(ids)).values({col: dup.id}))
    voided = [uuid.UUID(i) for i in cand.moved.get("voided_obligations", [])]
    if voided:
        db.execute(update(TaxObligation).where(TaxObligation.id.in_(voided)).values(status="open"))
    for model in (TaxReturn, Payment):
        db.execute(update(model).where(model.taxpayer_id.in_([cand.survivor_id, dup.id])).values(obligation_id=None))
    dup.merged_into_id = None
    cand.status = "rolled_back"
    audit.record(
        db, tenant_id=cand.tenant_id, actor_id=user_id, actor_role=role, action="merge.rolled_back",
        resource_type="merge_candidate", resource_id=cand.id, details={"reason": reason},
    )
    return cand
