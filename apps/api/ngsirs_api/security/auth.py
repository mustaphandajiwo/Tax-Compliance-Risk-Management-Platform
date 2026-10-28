"""OIDC bearer-token authentication.

Production verifies tokens from the state identity provider (Keycloak or
equivalent) against its JWKS. Demo and test environments may use the built-in
development issuer, which signs with a local RSA key but goes through exactly
the same verification path.

Required claims: sub, preferred_username, tenant (code), tenant_id, roles,
purposes; amr must contain "mfa" when MFA is required.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import new_session
from ..errors import ApiError, forbidden
from .crypto import dev_jwt_key
from .rbac import PURPOSES, ROLES, has_permission


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    display_name: str
    tenant_id: uuid.UUID
    tenant_code: str
    roles: tuple[str, ...]
    purposes: tuple[str, ...] = ()
    lga_scope: tuple[str, ...] = ()
    mfa: bool = False
    kind: str = "user"  # user | service
    claims: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def can(self, permission: str) -> bool:
        return has_permission(self.roles, permission)

    @property
    def actor_id(self) -> str:
        return self.username


def issue_dev_token(
    username: str,
    display_name: str,
    tenant_id: uuid.UUID,
    tenant_code: str,
    roles: list[str],
    purposes: list[str],
    lga_scope: list[str] | None = None,
    ttl: int | None = None,
) -> str:
    s = get_settings()
    if not s.dev_auth_enabled:
        raise forbidden("Development issuer is disabled")
    now = int(time.time())
    claims = {
        "iss": s.oidc_issuer,
        "aud": s.oidc_audience,
        "sub": f"dev|{username}",
        "iat": now,
        "exp": now + (ttl or s.token_ttl_seconds),
        "preferred_username": username,
        "name": display_name,
        "tenant": tenant_code,
        "tenant_id": str(tenant_id),
        "roles": roles,
        "purposes": purposes,
        "lga_scope": lga_scope or [],
        "amr": ["pwd", "mfa"],
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, dev_jwt_key(), algorithm="RS256", headers={"kid": "ngsirs-dev"})


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        if s.oidc_jwks_url:
            key: Any = _jwks_client(s.oidc_jwks_url).get_signing_key_from_jwt(token).key
        elif s.dev_auth_enabled:
            key = dev_jwt_key().public_key()
        else:
            raise ApiError(401, "unauthorized", "No token verifier configured")
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=s.oidc_audience,
            issuer=s.oidc_issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "token_expired", "Access token expired") from None
    except jwt.PyJWTError as exc:
        raise ApiError(401, "unauthorized", f"Invalid access token: {exc}") from None
    return claims


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    s = get_settings()
    try:
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
        tenant_code = str(claims["tenant"])
    except (KeyError, ValueError):
        raise ApiError(401, "unauthorized", "Token lacks organisation scope") from None
    roles = tuple(r for r in claims.get("roles", []) if r in ROLES)
    if not roles:
        raise forbidden("Token carries no recognised role")
    mfa = "mfa" in (claims.get("amr") or [])
    if s.require_mfa and not mfa and claims.get("token_use") != "service":
        raise ApiError(401, "mfa_required", "Multi-factor authentication is required")
    return Principal(
        sub=str(claims["sub"]),
        username=str(claims.get("preferred_username") or claims["sub"]),
        display_name=str(claims.get("name") or claims.get("preferred_username") or ""),
        tenant_id=tenant_id,
        tenant_code=tenant_code,
        roles=roles,
        purposes=tuple(p for p in claims.get("purposes", []) if p in PURPOSES),
        lga_scope=tuple(claims.get("lga_scope") or ()),
        mfa=mfa,
        kind="service" if claims.get("token_use") == "service" else "user",
        claims=claims,
    )


def get_principal(request: Request, authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "Bearer token required")
    principal = principal_from_claims(decode_token(authorization.split(" ", 1)[1].strip()))
    request.state.principal = principal
    return principal


def require(permission: str):  # type: ignore[no-untyped-def]
    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.can(permission):
            raise forbidden(f"Role lacks permission '{permission}'")
        return principal

    return dep


def get_db(principal: Principal = Depends(get_principal)):  # type: ignore[no-untyped-def]
    session: Session = new_session(principal.tenant_id)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def declared_purpose(principal: Principal, purpose: str | None, *, required: bool = True) -> str | None:
    """Purpose-based access: the request must name a purpose the token grants."""
    if purpose is None:
        if required:
            raise forbidden("This action requires an X-Purpose header", {"allowed": list(principal.purposes)})
        return None
    if purpose not in PURPOSES:
        raise forbidden(f"Unknown purpose '{purpose}'")
    if purpose not in principal.purposes:
        raise forbidden(f"Purpose '{purpose}' is not granted to this user")
    return purpose
