"""Encrypted object storage for raw source files, snapshots and evidence packets.

Objects are encrypted client-side (AES-GCM, key from the vault) before they
reach the backend, so an exposed bucket or disk does not expose taxpayer data.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from .config import get_settings
from .security.crypto import decrypt, encrypt


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("object key escapes storage root")
        return p

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(encrypt(data, key.encode()))

    def get(self, key: str) -> bytes:
        return decrypt(self._path(key).read_bytes(), key.encode())

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Store:
    def __init__(self) -> None:
        import boto3

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
        )

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=encrypt(data, key.encode()), ServerSideEncryption="AES256"
        )

    def get(self, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return decrypt(body, key.encode())

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


@lru_cache
def get_store() -> ObjectStore:
    s = get_settings()
    return S3Store() if s.storage_backend == "s3" else LocalStore(s.storage_path)
