"""Canonical JSON hashing for rule sets, snapshots and audit events."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def _default(o: Any) -> Any:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return format(o, "f")
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False)


def sha256_hex(obj: Any) -> str:
    data = obj if isinstance(obj, bytes) else canonical_json(obj).encode()
    return hashlib.sha256(data).hexdigest()


def rule_set_hash(rules: list[dict[str, Any]], legal_versions: list[dict[str, Any]]) -> str:
    return sha256_hex(
        {
            "rules": sorted(rules, key=lambda r: (r["id"], r["version"])),
            "legal": sorted(legal_versions, key=lambda v: (v["code"], v["version"])),
        }
    )
