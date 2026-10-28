"""Rule registry with maker-checker governance (FR-007, Tech Spec section 16).

draft (validated) -> backtest -> submit -> approvals (legal + compliance manager,
both independent of the author) -> approved -> activate -> (retire / rollback)

An approved version is immutable (database trigger); changing a rule means a
new version. Every approval is an Ed25519-signed decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine import RuleValidationError, validate_rule
from risk_engine.hashing import canonical_json, sha256_hex

from .. import audit
from ..errors import conflict, forbidden, not_found, unprocessable
from ..models import RuleDefinitionRow, RuleVersion
from ..security import crypto
from ..security.auth import Principal
from . import legal

REQUIRED_APPROVER_ROLES = ("legal_approver", "compliance_manager")


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def validation_report(expression: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_rule(expression)
        return {"valid": True, "errors": []}
    except RuleValidationError as exc:
        return {"valid": False, "errors": exc.errors}


def draft(db: Session, actor: Principal, expression: dict[str, Any], change_note: str) -> RuleVersion:
    report = validation_report(expression)
    if not report["valid"]:
        raise unprocessable("Rule definition failed validation", report["errors"])
    code, version = expression["id"], expression["version"]
    definition = db.execute(
        select(RuleDefinitionRow).where(RuleDefinitionRow.rule_code == code)
    ).scalar_one_or_none()
    if definition is None:
        raise not_found(f"Rule {code} in catalogue")
    versions = list(db.execute(select(RuleVersion).where(RuleVersion.rule_code == code)).scalars())
    if any(_semver(v.version) >= _semver(version) for v in versions):
        raise conflict(
            f"Version {version} must be greater than existing versions",
            {"existing": sorted(v.version for v in versions)},
        )
    obligation = expression.get("obligation_ref")
    rv = RuleVersion(
        tenant_id=actor.tenant_id,
        rule_code=code,
        version=version,
        expression_json=expression,
        content_hash=sha256_hex(expression),
        legal_ref=obligation.split("@")[0] if obligation else None,
        status="validated",
        author_id=actor.actor_id,
        change_note=change_note,
        validation_report=report,
        approvals=[],
    )
    db.add(rv)
    db.flush()
    audit.record(
        db,
        actor,
        "rule.version_drafted",
        f"rule:{code}@{version}",
        {"change_note": change_note},
        after=rv.content_hash,
    )
    return rv


def submit(db: Session, actor: Principal, rv: RuleVersion) -> RuleVersion:
    if rv.status != "validated":
        raise conflict(f"Version is {rv.status}; only validated versions can be submitted")
    if rv.author_id != actor.actor_id:
        raise forbidden("Only the author submits a version for approval")
    if not rv.backtest_report:
        raise conflict("Run a backtest before submitting for approval")
    rv.status = "pending_approval"
    db.flush()
    audit.record(db, actor, "rule.version_submitted", f"rule:{rv.rule_code}@{rv.version}", {})
    return rv


def approve(db: Session, actor: Principal, rv: RuleVersion, note: str, as_role: str) -> RuleVersion:
    if rv.status != "pending_approval":
        raise conflict(f"Version is {rv.status}, not pending approval")
    if as_role not in REQUIRED_APPROVER_ROLES or as_role not in actor.roles:
        raise forbidden(f"Approval must be given as one of your roles: {', '.join(REQUIRED_APPROVER_ROLES)}")
    if rv.author_id == actor.actor_id:
        raise forbidden("Maker-checker: the author cannot approve their own rule version")
    if any(a["actor"] == actor.actor_id for a in rv.approvals):
        raise forbidden("Two-person rule: one person cannot give both approvals")
    if any(a["role"] == as_role for a in rv.approvals):
        raise conflict(f"{as_role} approval already recorded")
    if as_role == "legal_approver" and rv.legal_ref:
        if not legal.versions_for(db, rv.legal_ref) or not any(
            v.status == "approved" for v in legal.versions_for(db, rv.legal_ref)
        ):
            raise conflict(f"No approved legal version exists for {rv.legal_ref}")
    decision = {
        "rule": rv.rule_code,
        "version": rv.version,
        "content_hash": rv.content_hash,
        "actor": actor.actor_id,
        "role": as_role,
        "at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    decision["signature"] = crypto.sign(canonical_json(decision).encode())
    decision["key_id"] = crypto.signing_key_id()
    rv.approvals = [*rv.approvals, decision]
    if {a["role"] for a in rv.approvals} >= set(REQUIRED_APPROVER_ROLES):
        rv.status = "approved"
    db.flush()
    audit.record(
        db,
        actor,
        "rule.version_approved",
        f"rule:{rv.rule_code}@{rv.version}",
        {"role": as_role, "note": note, "fully_approved": rv.status == "approved"},
        after=rv.content_hash,
    )
    return rv


def reject(db: Session, actor: Principal, rv: RuleVersion, note: str) -> RuleVersion:
    if rv.status not in ("pending_approval", "validated"):
        raise conflict(f"Version is {rv.status}")
    if rv.author_id == actor.actor_id:
        raise forbidden("The author cannot reject their own version; withdraw it instead")
    rv.status = "rejected"
    db.flush()
    audit.record(db, actor, "rule.version_rejected", f"rule:{rv.rule_code}@{rv.version}", {"note": note})
    return rv


def activate(db: Session, actor: Principal, rv: RuleVersion, reason: str) -> RuleVersion:
    if rv.status not in ("approved", "retired"):
        raise conflict(f"Version is {rv.status}; only approved versions can be activated")
    if rv.author_id == actor.actor_id:
        raise forbidden("Segregation of duties: the author cannot activate their own version")
    definition = db.execute(
        select(RuleDefinitionRow).where(RuleDefinitionRow.rule_code == rv.rule_code)
    ).scalar_one()
    previous = db.get(RuleVersion, definition.active_version_id) if definition.active_version_id else None
    if previous is not None and previous.id != rv.id:
        previous.status = "retired"
    rv.status = "active"
    rv.activated_by = actor.actor_id
    rv.activated_at = datetime.now(UTC)
    definition.active_version_id = rv.id
    db.flush()
    audit.record(
        db,
        actor,
        "rule.version_activated",
        f"rule:{rv.rule_code}@{rv.version}",
        {"reason": reason, "previous": f"{previous.rule_code}@{previous.version}" if previous else None},
        before=previous.content_hash if previous else None,
        after=rv.content_hash,
    )
    return rv


def rollback(db: Session, actor: Principal, rule_code: str, reason: str) -> RuleVersion:
    definition = db.execute(
        select(RuleDefinitionRow).where(RuleDefinitionRow.rule_code == rule_code)
    ).scalar_one_or_none()
    if definition is None or definition.active_version_id is None:
        raise not_found("Active rule")
    current = db.get(RuleVersion, definition.active_version_id)
    assert current is not None
    retired = list(db.execute(
            select(RuleVersion).where(RuleVersion.rule_code == rule_code, RuleVersion.status == "retired")
        ).scalars())
    if not retired:
        raise conflict("No earlier approved version to roll back to")
    target = max(retired, key=lambda v: _semver(v.version))
    current.status = "retired"
    target.status = "active"
    target.activated_by = actor.actor_id
    target.activated_at = datetime.now(UTC)
    definition.active_version_id = target.id
    db.flush()
    audit.record(
        db,
        actor,
        "rule.rolled_back",
        f"rule:{rule_code}",
        {"from": current.version, "to": target.version, "reason": reason},
        before=current.content_hash,
        after=target.content_hash,
    )
    return target


def diff(a: Any, b: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[dict[str, Any]] = []
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}" if path else k
            if k not in a:
                out.append({"path": p, "change": "added", "to": b[k]})
            elif k not in b:
                out.append({"path": p, "change": "removed", "from": a[k]})
            else:
                out.extend(diff(a[k], b[k], p))
        return out
    if a != b:
        return [{"path": path, "change": "changed", "from": a, "to": b}]
    return []


def version_payload(rv: RuleVersion) -> dict[str, Any]:
    return {
        "id": str(rv.id),
        "rule_code": rv.rule_code,
        "version": rv.version,
        "status": rv.status,
        "content_hash": rv.content_hash,
        "legal_ref": rv.legal_ref,
        "author": rv.author_id,
        "change_note": rv.change_note,
        "approvals": rv.approvals,
        "activated_by": rv.activated_by,
        "activated_at": rv.activated_at.isoformat() if rv.activated_at else None,
        "validation": rv.validation_report,
        "backtest": rv.backtest_report,
        "definition": rv.expression_json,
        "created_at": rv.created_at.isoformat() if rv.created_at else None,
    }


def get_version(db: Session, version_id: uuid.UUID) -> RuleVersion:
    rv = db.get(RuleVersion, version_id)
    if rv is None:
        raise not_found("Rule version")
    return rv
