"""Row validation, typing and quarantine decisions.

Outcomes per row:
- accepted:    typed values ready for canonical storage
- quarantined: kept with provenance but excluded from evaluation until a data
               steward resolves it (invalid identifier, invalid period,
               unknown employer, conflicting duplicate ...). Quarantine never
               produces taxpayer risk; it produces data-quality signals.
- rejected:    structurally unusable (unparseable required field)
- duplicate:   exact repeat of an earlier row in the same file (ignored)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from typing import Any

from .feeds import FEEDS, FeedProfile

WAT = timezone(timedelta(hours=1), "WAT")  # Africa/Lagos, no DST
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")

# Reasons that quarantine rather than reject.
QUARANTINE_REASONS = {
    "invalid_period",
    "invalid_identifier",
    "unknown_employer",
    "conflicting_duplicate",
    "accepted_without_timestamp",
    "conflicting_identifier",
}


@dataclass
class ValidationContext:
    tin_pattern: str = r"^NGS-DEMO-TIN-\d{6}$"
    known_lgas: set[str] | None = None
    known_employers: set[str] | None = None
    tz: tzinfo = WAT


@dataclass
class RowResult:
    row_number: int
    status: str
    values: dict[str, Any]
    raw: dict[str, str]
    reasons: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    natural_id: str | None = None
    employer_ref: str | None = None
    content_hash: str = ""


@dataclass
class ValidationReport:
    feed_type: str
    header_errors: list[str]
    results: list[RowResult]
    mapping: dict[str, str]

    @property
    def rejected_file(self) -> bool:
        return bool(self.header_errors)

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {"accepted": 0, "quarantined": 0, "rejected": 0, "duplicate": 0}
        reasons: dict[str, int] = {}
        warnings: dict[str, int] = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
            for reason in r.reasons:
                reasons[reason] = reasons.get(reason, 0) + 1
            for m in r.messages:
                key = m.split(":", 1)[0]
                warnings[key] = warnings.get(key, 0) + 1
        total = len(self.results)
        return {
            "rows": total,
            **counts,
            "reasons": reasons,
            "warnings": warnings,
            "header_errors": self.header_errors,
            "completeness": round(counts["accepted"] / total, 4) if total else 0.0,
        }


def parse_period(v: str) -> str | None:
    m = PERIOD_RE.match(v.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}"


def parse_datetime(v: str, tz: tzinfo) -> datetime:
    dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def parse_bool(v: str) -> bool:
    s = v.strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    raise ValueError(f"not a boolean: {v!r}")


def check_headers(profile: FeedProfile, headers: list[str], mapping: dict[str, str]) -> list[str]:
    mapped = {mapping.get(h, h) for h in headers}
    return [f"missing required column '{c}'" for c in profile.required if c not in mapped]


def unmapped_columns(profile: FeedProfile, headers: list[str], mapping: dict[str, str]) -> list[str]:
    names = {c.name for c in profile.columns}
    return sorted(h for h in headers if mapping.get(h, h) not in names)


def _row_hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def validate_rows(
    feed_type: str,
    headers: list[str],
    rows: list[dict[str, str]],
    mapping: dict[str, str] | None,
    ctx: ValidationContext,
) -> ValidationReport:
    profile = FEEDS[feed_type]
    mapping = mapping or {}
    header_errors = check_headers(profile, headers, mapping)
    results: list[RowResult] = []
    if header_errors:
        return ValidationReport(feed_type, header_errors, results, mapping)

    tin_re = re.compile(ctx.tin_pattern)
    seen: dict[str, str] = {}
    for idx, raw in enumerate(rows, start=2):  # header is line 1
        canonical = {mapping.get(k, k): v for k, v in raw.items()}
        values: dict[str, Any] = {}
        reasons: list[str] = []
        messages: list[str] = []
        for col in profile.columns:
            v = (canonical.get(col.name) or "").strip()
            if not v:
                values[col.name] = None
                if col.required:
                    if col.type == "period":
                        reasons.append("invalid_period")
                    elif col.type == "identifier":
                        reasons.append("invalid_identifier")
                    else:
                        reasons.append(f"missing_required:{col.name}")
                continue
            try:
                if col.type == "str":
                    values[col.name] = v
                elif col.type == "int":
                    values[col.name] = int(v)
                elif col.type == "decimal":
                    d = Decimal(v.replace(",", ""))
                    if not d.is_finite():
                        raise InvalidOperation
                    values[col.name] = d.quantize(Decimal("0.01"))
                elif col.type == "date":
                    values[col.name] = date.fromisoformat(v[:10])
                elif col.type == "datetime":
                    values[col.name] = parse_datetime(v, ctx.tz)
                elif col.type == "bool":
                    values[col.name] = parse_bool(v)
                elif col.type == "period":
                    p = parse_period(v)
                    if p is None:
                        reasons.append("invalid_period")
                        messages.append(f"invalid_period: '{v}' is not YYYY-MM")
                    values[col.name] = p
                elif col.type == "enum":
                    if v not in col.values:
                        raise ValueError(f"'{v}' not one of {', '.join(col.values)}")
                    values[col.name] = v
                elif col.type == "identifier":
                    if not tin_re.match(v):
                        reasons.append("invalid_identifier")
                        messages.append("invalid_identifier: identifier fails issuing-authority format check")
                    values[col.name] = v
            except (ValueError, InvalidOperation) as exc:
                reasons.append(f"invalid_value:{col.name}")
                messages.append(f"invalid_value:{col.name}: {exc}")
                values[col.name] = None

        if ctx.known_lgas is not None and values.get("lga_code") and values["lga_code"] not in ctx.known_lgas:
            messages.append(f"unverified_lga: {values['lga_code']}")
        employer_ref = values.get(profile.employer_ref_column) if profile.employer_ref_column else None
        if (
            ctx.known_employers is not None
            and employer_ref
            and feed_type != "ngsirs_employer"
            and employer_ref not in ctx.known_employers
        ):
            if feed_type == "ngsirs_payment":
                messages.append("unmatched_employer: payment reference does not resolve to a known employer")
            else:
                reasons.append("unknown_employer")
        if (
            feed_type == "ngsirs_paye_return"
            and values.get("status") == "accepted"
            and not values.get("accepted_at")
        ):
            reasons.append("accepted_without_timestamp")

        natural_parts = [str(values.get(k) or canonical.get(k) or "") for k in profile.natural_key]
        natural_id = "|".join(natural_parts) if all(natural_parts) else None
        content_hash = _row_hash(values)
        status = "accepted"
        if any(r.startswith(("missing_required", "invalid_value")) for r in reasons):
            status = "rejected"
        elif reasons:
            status = "quarantined"
        if natural_id is not None and status != "rejected":
            if natural_id in seen:
                if seen[natural_id] == content_hash:
                    status = "duplicate"
                else:
                    status = "quarantined"
                    reasons.append("conflicting_duplicate")
            else:
                seen[natural_id] = content_hash
        results.append(
            RowResult(
                idx,
                status,
                values,
                raw,
                reasons,
                messages,
                natural_id,
                str(employer_ref) if employer_ref else None,
                content_hash,
            )
        )
    return ValidationReport(feed_type, header_errors, results, mapping)
