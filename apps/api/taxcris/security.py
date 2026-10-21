"""Credentials, tokens, identifier hashing and masking."""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from .config import get_settings

_PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(rounds))
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.jwt_ttl_minutes)).timestamp()),
        "iss": "taxcris",
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer="taxcris")


def normalise_identifier(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def hash_identifier(salt: str, identifier_type: str, value: str) -> str:
    """Tenant-salted HMAC so identifiers can be matched without being stored in clear."""
    msg = f"{identifier_type}:{normalise_identifier(value)}".encode()
    return hmac.new(salt.encode(), msg, hashlib.sha256).hexdigest()


def mask_identifier(value: str) -> str:
    v = value.strip()
    if len(v) <= 4:
        return "*" * len(v)
    return "*" * (len(v) - 4) + v[-4:]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def new_salt() -> str:
    return secrets.token_hex(32)
