"""Risk model studio lifecycle: draft → pending_approval → approved (→ retired)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..models import RiskModel
from .scoring import DIMENSIONS


class FourEyesViolation(Exception):
    pass


def validate_weights(weights: dict[str, float]) -> None:
    unknown = set(weights) - set(DIMENSIONS)
    if unknown:
        raise ValueError(f"Unknown dimensions: {sorted(unknown)}")
    if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Weights must be non-negative and sum to a positive value")


def submit(db: Session, model: RiskModel, user_id: uuid.UUID, role: str) -> RiskModel:
    if model.status != "draft":
        raise ValueError("Only draft models can be submitted")
    model.status = "pending_approval"
    audit.record(db, tenant_id=model.tenant_id, actor_id=user_id, actor_role=role, action="risk_model.submitted",
                 resource_type="risk_model", resource_id=model.id, details={"version": model.version})
    return model


def approve(db: Session, model: RiskModel, user_id: uuid.UUID, role: str, reason: str) -> RiskModel:
    if model.status != "pending_approval":
        raise ValueError("Only pending models can be approved")
    if model.created_by == user_id:
        raise FourEyesViolation("An analyst cannot approve deployment of their own risk model")
    for other in db.execute(
        select(RiskModel).where(RiskModel.tenant_id == model.tenant_id, RiskModel.status == "approved")
    ).scalars():
        other.status = "retired"
    model.status, model.approved_by, model.approved_at = "approved", user_id, datetime.now(timezone.utc)
    audit.record(db, tenant_id=model.tenant_id, actor_id=user_id, actor_role=role, action="risk_model.approved",
                 resource_type="risk_model", resource_id=model.id,
                 details={"version": model.version, "reason": reason, "weights": model.weights, "thresholds": model.thresholds})
    return model


def rollback_to(db: Session, model: RiskModel, user_id: uuid.UUID, role: str, reason: str) -> RiskModel:
    """Reinstate a previously approved (now retired) version."""
    if model.status != "retired" or model.approved_by is None:
        raise ValueError("Only previously approved, retired versions can be reinstated")
    for other in db.execute(
        select(RiskModel).where(RiskModel.tenant_id == model.tenant_id, RiskModel.status == "approved")
    ).scalars():
        other.status = "retired"
    model.status = "approved"
    audit.record(db, tenant_id=model.tenant_id, actor_id=user_id, actor_role=role, action="risk_model.rolled_back",
                 resource_type="risk_model", resource_id=model.id, details={"version": model.version, "reason": reason})
    return model
