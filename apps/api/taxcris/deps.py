import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import audit
from .db import get_db
from .models import User
from .permissions import P, permissions_for
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    email: str
    full_name: str

    @property
    def permissions(self) -> frozenset[P]:
        return permissions_for(self.role)

    def can(self, perm: P) -> bool:
        return perm in self.permissions


def get_principal(
    db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active or str(user.tenant_id) != claims["tid"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled or not found")
    # Role is re-read from the database so revocations apply immediately.
    return Principal(user.id, user.tenant_id, user.role, user.email, user.full_name)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def deny(db: Session, principal: Principal, action: str, resource_type: str, resource_id=None, reason: str = "") -> HTTPException:
    """Record a denied attempt in its own transaction and return the exception to raise."""
    db.rollback()
    audit.record(
        db,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome="denied",
        details={"reason": reason} if reason else {},
    )
    db.commit()
    return HTTPException(status.HTTP_403_FORBIDDEN, reason or "Permission denied")


def require(*perms: P):
    def dep(request: Request, db: DB, principal: CurrentPrincipal) -> Principal:
        missing = [p for p in perms if not principal.can(p)]
        if missing:
            raise deny(
                db,
                principal,
                "access.denied",
                "endpoint",
                f"{request.method} {request.url.path}",
                f"Missing permission: {', '.join(missing)}",
            )
        return principal

    return dep
