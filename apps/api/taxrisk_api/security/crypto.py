"""Field encryption, keyed identifier tokens and evidence signing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings

_VERSION = b"\x01"


def _key(b64: str) -> bytes:
    key = base64.b64decode(b64)
    if len(key) != 32:
        raise ValueError("encryption keys must be 32 bytes")
    return key


def encrypt(plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return _VERSION + nonce + AESGCM(_key(get_settings().data_key_b64)).encrypt(nonce, plaintext, aad)


def decrypt(blob: bytes, aad: bytes = b"") -> bytes:
    if blob[:1] != _VERSION:
        raise ValueError("unknown ciphertext version")
    return AESGCM(_key(get_settings().data_key_b64)).decrypt(blob[1:13], blob[13:], aad)


def normalise_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def identifier_token(value: str, purpose: str = "id") -> str:
    """Keyed, non-reversible token used for matching without decrypting."""
    msg = f"{purpose}:{normalise_identifier(value)}".encode()
    return hmac.new(_key(get_settings().token_key_b64), msg, hashlib.sha256).hexdigest()


def name_token(name: str) -> str:
    return identifier_token(" ".join(sorted(re.findall(r"[a-z0-9]+", name.lower()))), "name")


def mask(value: str) -> str:
    v = normalise_identifier(value)
    return ("*" * max(0, len(v) - 4)) + v[-4:]


def _load_or_create(path: str, factory, loader):  # type: ignore[no-untyped-def]
    p = Path(path)
    if p.exists():
        return loader(p.read_bytes())
    if get_settings().environment == "production":
        raise RuntimeError(f"key file {path} missing; production keys must be provisioned from the vault")
    key = factory()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    os.chmod(p, 0o600)
    return key


@lru_cache
def evidence_signing_key() -> ed25519.Ed25519PrivateKey:
    key: ed25519.Ed25519PrivateKey = _load_or_create(
        get_settings().signing_key_path,
        ed25519.Ed25519PrivateKey.generate,
        lambda b: serialization.load_pem_private_key(b, password=None),
    )
    return key


def signing_key_id() -> str:
    pub = (
        evidence_signing_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return hashlib.sha256(pub).hexdigest()[:16]


def sign(data: bytes) -> str:
    return base64.b64encode(evidence_signing_key().sign(data)).decode()


def verify_signature(data: bytes, signature_b64: str) -> bool:
    try:
        evidence_signing_key().public_key().verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:
        return False


@lru_cache
def dev_jwt_key() -> rsa.RSAPrivateKey:
    key: rsa.RSAPrivateKey = _load_or_create(
        get_settings().jwt_key_path,
        lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048),
        lambda b: serialization.load_pem_private_key(b, password=None),
    )
    return key
