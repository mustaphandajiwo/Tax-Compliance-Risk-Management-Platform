"""Tenant bootstrap: NGSIRS reference data, synthetic legal versions, rule catalogue and users.

Everything seeded here is SYNTHETIC. Legal parameters are placeholders that an
NGSIRS legal officer must replace with values from authenticated texts before
any production activation; they are labelled as such wherever they appear.
"""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from risk_engine.catalogue import CATALOGUE
from risk_engine.hashing import canonical_json, sha256_hex
from risk_engine.rulepack import load_pilot_pack_raw

from . import audit
from .db import new_session, resolve_tenant_id
from .models import (
    AppUser,
    DataSource,
    LegalInstrument,
    LegalRuleVersion,
    Lga,
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

NIGER_STATE_LGAS = [
    "Agaie",
    "Agwara",
    "Bida",
    "Borgu",
    "Bosso",
    "Chanchaga",
    "Edati",
    "Gbako",
    "Gurara",
    "Katcha",
    "Kontagora",
    "Lapai",
    "Lavun",
    "Magama",
    "Mariga",
    "Mashegu",
    "Mokwa",
    "Munya",
    "Paikoro",
    "Rafi",
    "Rijau",
    "Shiroro",
    "Suleja",
    "Tafa",
    "Wushishi",
]
PILOT_LGAS = {"Bosso", "Chanchaga"}  # Minna


def lga_code(name: str) -> str:
    return name[:3].upper()


DEFAULT_SETTINGS: dict[str, Any] = {
    "operating_mode": "operational",
    "confidence_floor": 0.9,
    "processing_window_days": 5,
    "tin_pattern": r"^NGS-DEMO-TIN-\d{6}$",
    "identity": {"probabilistic_threshold": 0.98, "approved_by": "seed:data.governance (SYNTHETIC)"},
    "approved_templates": {
        "PAYE_RETURN_REMINDER_V1": "SYNTHETIC TEMPLATE: Reminder that the PAYE employer return for {period} is "
        "outstanding. If you have filed, please share your acknowledgement.",
        "PAYE_ASSISTANCE_OFFER_V1": "SYNTHETIC TEMPLATE: NGSIRS can help you file PAYE returns on time.",
        "PAYE_PAYMENT_ENGAGEMENT_V1": "SYNTHETIC TEMPLATE: Our records do not yet show a PAYE remittance for "
        "{period}. If you have paid, please send the payment reference.",
    },
    "branding": {
        "product": "NGSIRS Compliance Risk Management Platform",
        "owner": "Niger State Internal Revenue Service",
        "logo": None,
    },
}

DATA_SOURCES = [
    (
        "ngsirs_registration",
        ["ngsirs_taxpayer", "ngsirs_employer", "ngsirs_obligation", "ngsirs_extension"],
        "NGSIRS taxpayer & employer registration system",
        True,
        False,
        True,
    ),
    ("ngsirs_etax_portal", ["ngsirs_paye_return"], "NGSIRS e-tax filing portal", True, False, True),
    (
        "ngsirs_legacy_register",
        ["ngsirs_paye_return"],
        "Legacy manual returns register (office capture)",
        False,
        False,
        True,
    ),
    ("ngsirs_treasury", ["ngsirs_payment"], "NGSIRS treasury / collection reconciliation", True, False, True),
    ("ngsirs_bank_feed", ["ngsirs_payment"], "Collecting bank settlement feed", False, False, True),
    ("ngsirs_assessment_ledger", ["ngsirs_assessment"], "NGSIRS assessment ledger", True, False, True),
    (
        "external_business_licensing",
        ["ngsirs_employer"],
        "External business licensing extract (NOT AUTHORISED)",
        False,
        True,
        False,
    ),
]

INSTRUMENTS = [
    (
        "PRIOR-PAYE-LAW",
        "Previously applicable PAYE law (for tax periods before 1 January 2026)",
        "Federal / State",
        "NG",
        "pending_legal_confirmation",
        "Pre-2026 periods must use the previously applicable law. Text and provisions to be supplied by NGSIRS legal.",
    ),
    (
        "NTAA-2025",
        "Nigeria Tax Administration Act 2025",
        "Federal",
        "NG",
        "pending_legal_confirmation",
        "Federal baseline; sections 13-15 and 87-89 to be reviewed by NGSIRS legal officers.",
    ),
    (
        "NS-TACL-2023",
        "Niger State Tax Administration and Consolidation Law 2023 (as amended)",
        "Niger State",
        "NG-NI",
        "pending_legal_confirmation",
        "Full official legislation and amendment history required from NGSIRS legal team before production.",
    ),
]

# (code, version, instrument, from, to, parameters) - SYNTHETIC placeholders, not statements of law.
LEGAL_VERSIONS = [
    (
        "PAYE_EMPLOYER_MONTHLY_RETURN",
        "2020.1-SYN",
        "PRIOR-PAYE-LAW",
        date(2020, 1, 1),
        date(2025, 12, 31),
        {"due_day_of_following_month": 10},
    ),
    (
        "PAYE_EMPLOYER_MONTHLY_RETURN",
        "2026.1-SYN",
        "NTAA-2025",
        date(2026, 1, 1),
        None,
        {"due_day_of_following_month": 15},
    ),
    (
        "PAYE_EMPLOYER_REMITTANCE",
        "2020.1-SYN",
        "PRIOR-PAYE-LAW",
        date(2020, 1, 1),
        date(2025, 12, 31),
        {"due_day_of_following_month": 10},
    ),
    (
        "PAYE_EMPLOYER_REMITTANCE",
        "2026.1-SYN",
        "NTAA-2025",
        date(2026, 1, 1),
        None,
        {"due_day_of_following_month": 10},
    ),
    (
        "PAYE_ASSESSMENT",
        "2020.1-SYN",
        "PRIOR-PAYE-LAW",
        date(2020, 1, 1),
        date(2025, 12, 31),
        {"payment_days_after_service": 30},
    ),
    (
        "PAYE_ASSESSMENT",
        "2026.1-SYN",
        "NTAA-2025",
        date(2026, 1, 1),
        None,
        {"payment_days_after_service": 30},
    ),
]

RETENTION = [
    (
        "raw_source_files",
        2555,
        "Tax records retention (placeholder: confirm statutory period with NGSIRS legal)",
    ),
    ("findings_and_cases", 2555, "Compliance decision records (placeholder)"),
    ("audit_events", 3650, "Accountability; tamper-evident chain (placeholder)"),
    ("access_logs", 730, "Security monitoring (placeholder)"),
]


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
                hosting_mode="state_hosted_single_tenant",
                legal_config_version="SYNTHETIC-2026.10",
                settings=settings if settings is not None else DEFAULT_SETTINGS,
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


def seed_reference(db: Session, tid: uuid.UUID) -> None:
    if db.execute(select(Lga)).first():
        return
    for n in NIGER_STATE_LGAS:
        db.add(Lga(tenant_id=tid, code=lga_code(n), name=n, verified=False, pilot=n in PILOT_LGAS))
    for n in NIGER_STATE_LGAS:
        db.add(
            TaxOffice(
                tenant_id=tid,
                code=f"OFF-{lga_code(n)}",
                name=f"{n} Tax Office (SYNTHETIC)",
                lga_code=lga_code(n),
            )
        )
    for name, feeds, owner, sor, external, enabled in DATA_SOURCES:
        db.add(
            DataSource(
                tenant_id=tid,
                source_name=name,
                feed_types=feeds,
                system_of_record=sor,
                owner=owner,
                data_sharing_basis="" if external else "Internal NGSIRS system (SYNTHETIC demo data)",
                permitted_purpose="PAYE compliance risk management",
                freshness_sla_days=7,
                is_external=external,
                enabled=enabled,
            )
        )
    instruments = {}
    for code, title, authority, juris, status, note in INSTRUMENTS:
        inst = LegalInstrument(
            tenant_id=tid,
            code=code,
            title=title,
            authority=authority,
            jurisdiction=juris,
            status=status,
            source_note=note,
            is_synthetic=True,
        )
        db.add(inst)
        db.flush()
        instruments[code] = inst
    now = datetime.now(UTC)
    for code, version, inst, eff_from, eff_to, params in LEGAL_VERSIONS:
        spec = legal.OBLIGATION_CODES[code]
        provision = f"SYNTHETIC placeholder provision under {inst} - replace with authenticated reference"
        row = {
            "code": code,
            "version": version,
            "effective_from": eff_from,
            "effective_to": eff_to,
            "parameters": params,
            "provision_ref": provision,
            "jurisdiction": "NG-NI",
        }
        db.add(
            LegalRuleVersion(
                tenant_id=tid,
                code=code,
                version=version,
                tax_type=spec["tax_type"],
                obligation_type=spec["obligation_type"],
                instrument_id=instruments[inst].id,
                provision_ref=provision,
                jurisdiction="NG-NI",
                effective_from=eff_from,
                effective_to=eff_to,
                parameters=params,
                status="approved",
                drafted_by=SYNTHETIC_POLICY,
                approved_by=SYNTHETIC_LEGAL,
                approved_at=now,
                approval_note="SYNTHETIC demo approval. Real activation requires NGSIRS legal sign-off.",
                content_hash=legal.content_hash(row),
                is_synthetic=True,
            )
        )
    for data_class, days, basis in RETENTION:
        db.add(RetentionPolicy(tenant_id=tid, data_class=data_class, retain_days=days, legal_basis=basis))
    db.flush()
    seed_rules(db, tid)
    audit.record(
        db,
        SYSTEM,
        "tenant.reference_seeded",
        f"tenant:{tid}",
        {"lgas": len(NIGER_STATE_LGAS), "legal_versions": len(LEGAL_VERSIONS)},
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
            change_note="NGSIRS pilot pack v1 (Tech Spec section 23)",
            validation_report={"valid": True, "errors": []},
            backtest_report={"note": "Golden fixture test: tests/integration/test_golden_fixture.py"},
            approvals=approvals,
            activated_by="seed:compliance.manager (SYNTHETIC)",
            activated_at=now,
        )
        db.add(rv)
        db.flush()
        d.active_version_id = rv.id


def seed_users(db: Session, tid: uuid.UUID, users_csv: Path) -> int:
    existing = set(db.execute(select(AppUser.username)).scalars())
    n = 0
    with users_csv.open() as fh:
        for row in csv.DictReader(fh):
            if row["username"] in existing:
                continue
            db.add(
                AppUser(
                    tenant_id=tid,
                    username=row["username"],
                    display_name=row["display_name"],
                    roles=row["roles"].split(";"),
                    unit=row.get("unit") or None,
                    lga_scope=[x for x in (row.get("lga_scope") or "").split(";") if x] or None,
                    allowed_purposes=[x for x in (row.get("purposes") or "").split(";") if x],
                    is_synthetic=True,
                )
            )
            n += 1
    db.flush()
    return n


def seed_all(users_csv: Path, code: str = "NGSIRS") -> uuid.UUID:
    tid = bootstrap_tenant(code, "Niger State Internal Revenue Service")
    with new_session(tid) as db:
        seed_reference(db, tid)
        seed_users(db, tid, users_csv)
        db.commit()
    return tid
