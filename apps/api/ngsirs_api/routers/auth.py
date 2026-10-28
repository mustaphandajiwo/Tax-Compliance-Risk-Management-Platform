from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from .. import audit
from ..config import get_settings
from ..db import new_session, resolve_tenant_id
from ..errors import ApiError, forbidden
from ..models import AppUser, Tenant
from ..schemas import DevTokenRequest, DevUser, Me, TokenResponse
from ..security.auth import Principal, get_db, get_principal, issue_dev_token
from ..security.rbac import permissions_for

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _dev_only() -> None:
    s = get_settings()
    if not (s.dev_auth_enabled and s.is_demo()):
        raise forbidden("The development issuer is only available in demo and test environments")


@router.get("/auth/dev-users", response_model=list[DevUser], dependencies=[Depends(_dev_only)])
def dev_users() -> list[dict]:
    tid = resolve_tenant_id(get_settings().default_tenant_code)
    if tid is None:
        return []
    with new_session(tid) as db:
        users = db.execute(select(AppUser).where(AppUser.active).order_by(AppUser.username)).scalars()
        return [
            {"username": u.username, "display_name": u.display_name, "roles": u.roles, "unit": u.unit}
            for u in users
        ]


@router.post("/auth/dev-token", response_model=TokenResponse, dependencies=[Depends(_dev_only)])
def dev_token(body: DevTokenRequest) -> dict:
    s = get_settings()
    tid = resolve_tenant_id(s.default_tenant_code)
    if tid is None:
        raise ApiError(503, "not_initialised", "Tenant not initialised; run `ngsirs seed`")
    db = new_session(tid)
    try:
        user = db.execute(
            select(AppUser).where(AppUser.username == body.username, AppUser.active)
        ).scalar_one_or_none()
        if user is None:
            raise ApiError(401, "unauthorized", "Unknown or inactive user")
        token = issue_dev_token(
            user.username,
            user.display_name,
            tid,
            s.default_tenant_code,
            list(user.roles),
            list(user.allowed_purposes),
            list(user.lga_scope or []),
        )
        audit.record(
            db,
            user.username,
            "auth.dev_token_issued",
            f"user:{user.username}",
            {"roles": list(user.roles)},
            tenant_id=tid,
        )
        db.commit()
    finally:
        db.close()
    return {"access_token": token, "token_type": "Bearer", "expires_in": s.token_ttl_seconds}


@router.get("/me", response_model=Me)
def me(principal: Principal = Depends(get_principal), db=Depends(get_db)) -> dict:  # type: ignore[no-untyped-def]
    tenant = db.get(Tenant, principal.tenant_id)
    s = get_settings()
    return {
        "username": principal.username,
        "display_name": principal.display_name,
        "tenant": principal.tenant_code,
        "tenant_name": tenant.name if tenant else principal.tenant_code,
        "roles": list(principal.roles),
        "permissions": permissions_for(list(principal.roles)),
        "purposes": list(principal.purposes),
        "lga_scope": list(principal.lga_scope),
        "environment": s.environment,
        "synthetic_data": s.is_demo(),
        "operating_mode": ((tenant.settings if tenant else {}) or {}).get("operating_mode", "shadow"),
    }
