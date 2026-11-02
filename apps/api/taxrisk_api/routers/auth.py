from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from .. import audit
from ..config import get_settings
from ..db import new_session, resolve_tenant_id
from ..errors import ApiError, forbidden
from ..models import AppUser, Tenant
from ..schemas import Branding, DevTokenRequest, DevUser, Me, TokenResponse
from ..security.auth import Principal, get_db, get_principal, issue_dev_token
from ..security.rbac import permissions_for

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _dev_only() -> None:
    s = get_settings()
    if not (s.dev_auth_enabled and s.is_demo()):
        raise forbidden("The development issuer is only available in demo and test environments")


@router.get("/auth/branding", response_model=Branding)
def branding() -> dict:
    """Public: which authority this deployment serves, for the sign-in screen. Contains no tenant data."""
    s = get_settings()
    tid = resolve_tenant_id(s.default_tenant_code)
    name, short, fictional = s.default_tenant_code, s.default_tenant_code, False
    if tid is not None:
        with new_session(tid) as db:
            t = db.get(Tenant, tid)
            cfg = (t.settings if t else {}) or {}
            b = cfg.get("branding") or {}
            name = b.get("authority_name") or (t.name if t else name)
            short = b.get("short_name") or short
            fictional = bool(cfg.get("fictional"))
    return {
        "product_name": "Tax Compliance Risk Platform",
        "authority_name": name,
        "authority_short_name": short,
        "fictional_authority": fictional,
    }


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
        raise ApiError(503, "not_initialised", "Tenant not initialised; run `taxrisk seed`")
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
            list(user.area_scope or []),
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
    cfg = (tenant.settings if tenant else {}) or {}
    branding = cfg.get("branding") or {}
    return {
        "username": principal.username,
        "display_name": principal.display_name,
        "tenant": principal.tenant_code,
        "tenant_name": tenant.name if tenant else principal.tenant_code,
        "roles": list(principal.roles),
        "permissions": permissions_for(list(principal.roles)),
        "purposes": list(principal.purposes),
        "area_scope": list(principal.area_scope),
        "environment": s.environment,
        "synthetic_data": s.is_demo(),
        "operating_mode": cfg.get("operating_mode", "shadow"),
        "product_name": "Tax Compliance Risk Platform",
        "authority_name": branding.get("authority_name")
        or (tenant.name if tenant else principal.tenant_code),
        "authority_short_name": branding.get("short_name") or principal.tenant_code,
        "fictional_authority": bool(cfg.get("fictional")),
        "area_label": cfg.get("area_label", "Area"),
        "area_label_plural": cfg.get("area_label_plural", "Areas"),
        "currency": cfg.get("currency", "NGN"),
        "locale": cfg.get("locale", "en-NG"),
        "timezone": cfg.get("timezone", "Africa/Lagos"),
    }
