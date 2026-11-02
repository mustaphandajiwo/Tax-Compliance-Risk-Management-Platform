"""Tenant bootstrap from a jurisdiction pack: reference data, legal versions, rule catalogue and users.

Everything seeded here is SYNTHETIC. Legal parameters are placeholders that the authority's legal
officers must replace with values from authenticated texts before any production activation; they are
labelled as such wherever they appear.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.catalogue import CATALOGUE
from risk_engine.hashing import canonical_json, sha256_hex
from risk_engine.rulepack import load_pilot_pack_raw

from . import audit
from .db import new_session, resolve_tenant_id
from .jurisdiction import Pack, load_pack
from .models import (
    AdminArea,
    AppUser,
    DataSource,
    LegalInstrument,
    LegalRuleVersion,
    RetentionPolicy,
    RuleDefinitionRow,
    RuleVersion,
    TaxOffice,
    Tenant,
)
from .security import crypto
from .services import legal

SYSTEM = "system:seed"
SYNTHETIC_LEGAL = "seed:legal.reviewer (SYNTHETIC)"
SYNTHETIC_POLICY = "seed:policy.analyst (SYNTHETIC)"


def bootstrap_tenant(
    code: str, name: str, *, is_test_only: bool = False, settings: dict[str, Any] | None = None
) -> uuid.UUID:
    existing = resolve_tenant_id(code)
    if existing:
        return existing
    tid = uuid.uuid4()
    with new_session(tid) as db:
        db.add(
            Tenant(
                id=tid,
                code=code,
                name=name,
                is_test_only=is_test_only,
                hosting_mode="single_tenant",
                legal_config_version="SYNTHETIC-2026.10",
                settings=settings or {},
            )
        )
        db.flush()
        audit.record(
            db,
            SYSTEM,
            "tenant.created",
            f"tenant:{code}",
            {"name": name, "test_only": is_test_only},
            tenant_id=tid,
        )
        db.commit()
    return tid


def ensure_instruments(db: Session, tid: uuid.UUID, pack: Pack) -> None:
    """Add any instrument the pack gained since the tenant was seeded (idempotent)."""
    have = set(db.execute(select(LegalInstrument.code)).scalars())
    for i in pack.instruments:
        if i.code not in have:
            db.add(
                LegalInstrument(
                    tenant_id=tid,
                    code=i.code,
                    title=i.title,
                    authority=i.authority,
                    jurisdiction=i.jurisdiction,
                    status=i.status,
                    source_note=i.note,
                    is_synthetic=True,
                )
            )
    db.flush()


def seed_reference(db: Session, tid: uuid.UUID, pack: Pack) -> None:
    tenant = db.get(Tenant, tid)
    if tenant is not None:
        tenant.settings = pack.tenant_settings()
    if db.execute(select(AdminArea)).first():
        ensure_instruments(db, tid, pack)
        return
    for a in pack.areas:
        db.add(AdminArea(tenant_id=tid, code=a.code, name=a.name, verified=a.verified, pilot=a.pilot))
        db.add(
            TaxOffice(
                tenant_id=tid, code=f"OFF-{a.code}", name=f"{a.name} Tax Office (SYNTHETIC)", area_code=a.code
            )
        )
    for src in pack.data_sources:
        db.add(
            DataSource(
                tenant_id=tid,
                source_name=src.name,
                feed_types=src.feed_types,
                system_of_record=src.system_of_record,
                owner=src.owner,
                data_sharing_basis=src.data_sharing_basis
                if src.data_sharing_basis is not None
                else pack.data_sharing_basis,
                permitted_purpose="PAYE compliance risk management",
                freshness_sla_days=src.freshness_sla_days,
                is_external=src.external,
                enabled=src.enabled,
            )
        )
    ensure_instruments(db, tid, pack)
    instruments = {i.code: i for i in db.execute(select(LegalInstrument)).scalars()}
    now = datetime.now(UTC)
    for v in pack.legal_versions:
        spec = legal.OBLIGATION_CODES[v.code]
        provision = (
            f"SYNTHETIC placeholder provision under {v.instrument} - replace with authenticated reference"
        )
        row = {
            "code": v.code,
            "version": v.version,
            "effective_from": v.effective_from,
            "effective_to": v.effective_to,
            "parameters": v.parameters,
            "provision_ref": provision,
            "jurisdiction": pack.jurisdiction,
        }
        db.add(
            LegalRuleVersion(
                tenant_id=tid,
                code=v.code,
                version=v.version,
                tax_type=spec["tax_type"],
                obligation_type=spec["obligation_type"],
                instrument_id=instruments[v.instrument].id,
                provision_ref=provision,
                jurisdiction=pack.jurisdiction,
                effective_from=v.effective_from,
                effective_to=v.effective_to,
                parameters=v.parameters,
                status="approved",
                drafted_by=SYNTHETIC_POLICY,
                approved_by=SYNTHETIC_LEGAL,
                approved_at=now,
                approval_note="SYNTHETIC demo approval. Real activation requires the authority's legal sign-off.",
                content_hash=legal.content_hash(row),
                is_synthetic=True,
            )
        )
    for r in pack.retention:
        db.add(
            RetentionPolicy(
                tenant_id=tid, data_class=r.data_class, retain_days=r.retain_days, legal_basis=r.legal_basis
            )
        )
    db.flush()
    seed_rules(db, tid)
    audit.record(
        db,
        SYSTEM,
        "tenant.reference_seeded",
        f"tenant:{pack.code}",
        {"pack": pack.code, "areas": len(pack.areas), "legal_versions": len(pack.legal_versions)},
        tenant_id=tid,
    )


def seed_rules(db: Session, tid: uuid.UUID) -> None:
    pack = {r["id"]: r for r in load_pilot_pack_raw()}
    now = datetime.now(UTC)
    for entry in CATALOGUE:
        d = RuleDefinitionRow(
            tenant_id=tid,
            rule_code=entry.code,
            domain=entry.domain,
            title=entry.title,
            description=entry.note or entry.title,
            catalogue_status=entry.status,
            legacy_codes=[f"PRD:{entry.prd_code}"] if entry.prd_code else [],
            default_treatment=entry.default_treatment,
        )
        db.add(d)
        db.flush()
        expr = pack.get(entry.code)
        if expr is None:
            continue
        approvals = []
        for actor, role in (
            (SYNTHETIC_LEGAL, "legal_approver"),
            ("seed:compliance.manager (SYNTHETIC)", "compliance_manager"),
        ):
            decision = {
                "rule": entry.code,
                "version": expr["version"],
                "content_hash": sha256_hex(expr),
                "actor": actor,
                "role": role,
                "at": now.isoformat(),
                "note": "SYNTHETIC demo approval for shadow/demo use only",
            }
            decision["signature"] = crypto.sign(canonical_json(decision).encode())
            decision["key_id"] = crypto.signing_key_id()
            approvals.append(decision)
        rv = RuleVersion(
            tenant_id=tid,
            rule_code=entry.code,
            version=expr["version"],
            expression_json=expr,
            content_hash=sha256_hex(expr),
            legal_ref=expr["obligation_ref"].split("@")[0] if expr.get("obligation_ref") else None,
            status="active",
            author_id="seed:risk.analyst (SYNTHETIC)",
            change_note="PAYE pilot rule pack v1",
            validation_report={"valid": True, "errors": []},
            backtest_report={"note": "Golden fixture test: tests/integration/test_golden_fixture.py"},
            approvals=approvals,
            activated_by="seed:compliance.manager (SYNTHETIC)",
            activated_at=now,
        )
        db.add(rv)
        db.flush()
        d.active_version_id = rv.id


def seed_users(db: Session, tid: uuid.UUID, pack: Pack) -> int:
    existing = set(db.execute(select(AppUser.username)).scalars())
    n = 0
    for u in pack.fixture.users:
        if u.username in existing:
            continue
        db.add(
            AppUser(
                tenant_id=tid,
                username=u.username,
                display_name=u.display_name,
                roles=u.roles.split(";"),
                unit=u.unit or None,
                area_scope=[x for x in u.area_scope.split(";") if x] or None,
                allowed_purposes=[x for x in u.purposes.split(";") if x],
                is_synthetic=True,
            )
        )
        n += 1
    db.flush()
    return n


def seed_all(pack_name: str | None = None) -> uuid.UUID:
    from .config import get_settings
    from .services.integrations import seed_collection_platform

    settings = get_settings()
    pack = load_pack(pack_name or settings.default_pack)
    tid = bootstrap_tenant(pack.code, pack.name, settings=pack.tenant_settings())
    with new_session(tid) as db:
        seed_reference(db, tid, pack)
        seed_users(db, tid, pack)
        seed_collection_platform(db, tid, settings.collection_platform_url)
        db.commit()
    return tid
