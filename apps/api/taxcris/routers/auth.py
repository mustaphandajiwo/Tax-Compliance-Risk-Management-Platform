import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from .. import audit
from ..config import get_settings
from ..deps import DB, CurrentPrincipal, Principal, require
from ..models import Tenant, User
from ..permissions import ROLE_PERMISSIONS, P, Role
from ..schemas import LoginIn, MeOut, TenantOut, TokenOut, UserCreate, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/v1", tags=["auth & administration"])

# Simple per-client login throttle; production sits behind a gateway with proper rate limits.
_ATTEMPTS: dict[str, deque] = defaultdict(deque)
_WINDOW, _MAX = 300, 10


def _throttle(key: str) -> None:
    now = time.monotonic()
    q = _ATTEMPTS[key]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _MAX:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again later")
    q.append(now)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DB) -> TokenOut:
    _throttle(f"{request.client.host if request.client else '-'}:{body.email.lower()}")
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        if user is not None:
            audit.record(db, tenant_id=user.tenant_id, actor_id=user.id, actor_role=user.role, action="auth.login",
                         resource_type="user", resource_id=user.id, outcome="denied")
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    audit.record(db, tenant_id=user.tenant_id, actor_id=user.id, actor_role=user.role, action="auth.login",
                 resource_type="user", resource_id=user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.tenant_id, user.role),
                    expires_in=get_settings().jwt_ttl_minutes * 60)


@router.get("/auth/me", response_model=MeOut)
def me(principal: CurrentPrincipal, db: DB) -> MeOut:
    tenant = db.get(Tenant, principal.tenant_id)
    return MeOut(id=principal.user_id, email=principal.email, full_name=principal.full_name, role=principal.role,
                 permissions=sorted(p.value for p in principal.permissions), tenant=TenantOut.model_validate(tenant))


@router.get("/roles", response_model=dict[str, list[str]])
def role_matrix(_: CurrentPrincipal) -> dict[str, list[str]]:
    return {r.value: sorted(p.value for p in perms) for r, perms in ROLE_PERMISSIONS.items()}


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, principal: Annotated[Principal, Depends(require(P.USERS_READ))], role: str | None = None) -> list[User]:
    q = select(User).where(User.tenant_id == principal.tenant_id).order_by(User.full_name)
    if role:
        q = q.where(User.role == role)
    return list(db.execute(q).scalars())


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DB, principal: Annotated[Principal, Depends(require(P.USERS_MANAGE))]) -> User:
    try:
        Role(body.role)
    except ValueError:
        raise HTTPException(422, f"Unknown role {body.role}")
    if db.execute(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(409, "Email already in use")
    user = User(tenant_id=principal.tenant_id, email=body.email.lower(), full_name=body.full_name, role=body.role,
                password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.record(db, tenant_id=principal.tenant_id, actor_id=principal.user_id, actor_role=principal.role,
                 action="user.created", resource_type="user", resource_id=user.id, details={"role": body.role})
    db.commit()
    return user
