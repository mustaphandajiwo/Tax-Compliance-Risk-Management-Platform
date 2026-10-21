"""Seed a demo environment from the synthetic fixture (DEV/DEMO ONLY — never against production).

    taxcris-seed --reset            # drop & recreate schema, load Niger pilot + demo tenant
    taxcris-seed --reset --no-workflow

Creates two tenants (Niger State pilot and a small Kwara demo tenant used to show isolation),
one user per role (two where four-eyes control needs a second person), the versioned legal
catalogue, an approved risk model, imports the synthetic batches, runs PAYE and DA risk runs and
walks a few cases through the workflow so dashboards have outcomes.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, db as dbmod
from .config import today
from .db import Base
from .domain import cases, entity_resolution, ingestion, obligations, risk_models, scoring
from .models import Alert, LegalRule, RiskModel, RiskRun, Tenant, User
from .permissions import Role, permissions_for
from .security import hash_password, new_salt

DEMO_PASSWORD = "Demo-Pass-2026!"
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "synthetic" / "niger-pilot"

USERS = [
    ("admin", "Hauwa Ndayako", Role.STATE_ADMIN),
    ("steward", "Musa Gbate", Role.DATA_STEWARD),
    ("steward2", "Ladi Tsado", Role.DATA_STEWARD),
    ("analyst", "Zainab Bello", Role.RISK_ANALYST),
    ("analyst2", "Chinedu Okafor", Role.RISK_ANALYST),
    ("officer", "Yakubu Jiya", Role.COMPLIANCE_OFFICER),
    ("officer2", "Esther Kolo", Role.COMPLIANCE_OFFICER),
    ("manager", "Ibrahim Etsu", Role.COMPLIANCE_MANAGER),
    ("manager2", "Amina Shaba", Role.COMPLIANCE_MANAGER),
    ("audit", "Danjuma Yisa", Role.AUDIT_MANAGER),
    ("legal", "Fatima Abdullahi", Role.LEGAL_OFFICER),
    ("legal2", "Tunde Adeyemi", Role.LEGAL_OFFICER),
    ("exec", "Salihu Mamman", Role.EXECUTIVE),
    ("security", "Rakiya Garba", Role.SECURITY_AUDITOR),
]

LEGAL_RULES = [
    dict(rule_code="PAYE_MONTHLY_REMITTANCE", title="Employer PAYE monthly return and remittance", tax_type="PAYE",
         frequency="monthly", eligibility={"taxpayer_type": "business", "is_employer": True},
         deadline={"type": "days_after_period_end", "days": 10},
         evidence_requirements=["PAYE schedule", "remittance receipt"],
         citation="Personal Income Tax Act (as amended), s.81 — remittance within 10 days after month end. "
                  "ILLUSTRATIVE: requires tax counsel sign-off.",
         valid_from=date(2011, 1, 1), valid_to=None),
    dict(rule_code="PAYE_MONTHLY_REMITTANCE", title="Employer PAYE monthly return and remittance (2026 regime)",
         tax_type="PAYE", frequency="monthly", eligibility={"taxpayer_type": "business", "is_employer": True},
         deadline={"type": "days_after_period_end", "days": 10},
         evidence_requirements=["PAYE schedule", "remittance receipt"],
         citation="Nigeria Tax Administration Act 2025 (effective 1 Jan 2026) — PLACEHOLDER citation pending legal "
                  "review; deadline carried over unchanged.",
         valid_from=date(2026, 1, 1), valid_to=None),
    dict(rule_code="DA_ANNUAL_SELF_ASSESSMENT", title="Direct assessment annual self-assessment return", tax_type="DA",
         frequency="annual", eligibility={"taxpayer_type": "individual", "self_employed": True},
         deadline={"type": "fixed_date_following_year", "month": 3, "day": 31},
         evidence_requirements=["self-assessment form", "statement of income"],
         citation="Personal Income Tax Act (as amended), s.41 — return within 90 days of the year of assessment. "
                  "ILLUSTRATIVE: requires tax counsel sign-off.",
         valid_from=date(2011, 1, 1), valid_to=None),
    dict(rule_code="DA_ANNUAL_SELF_ASSESSMENT", title="Direct assessment annual return (2026 regime)", tax_type="DA",
         frequency="annual", eligibility={"taxpayer_type": "individual", "self_employed": True},
         deadline={"type": "fixed_date_following_year", "month": 3, "day": 31},
         evidence_requirements=["self-assessment form", "statement of income"],
         citation="Nigeria Tax Administration Act 2025 — PLACEHOLDER citation pending legal review.",
         valid_from=date(2026, 1, 1), valid_to=None),
]


def create_tenant(db: Session, code: str, name: str, domain: str) -> tuple[Tenant, dict[str, User]]:
    t = Tenant(state_code=code, name=name, legal_jurisdiction=f"{name}, Federal Republic of Nigeria",
               identifier_salt=new_salt(), config={"sla_days": {}, "pilot": code == "NI"})
    db.add(t)
    db.flush()
    users = {}
    pw = hash_password(DEMO_PASSWORD)
    for handle, full_name, role in USERS:
        u = User(tenant_id=t.id, email=f"{handle}@{domain}", full_name=full_name, role=role.value, password_hash=pw)
        db.add(u)
        users[handle] = u
    db.flush()
    audit.record(db, tenant_id=t.id, action="tenant.created", resource_type="tenant", resource_id=t.id,
                 details={"state_code": code, "users": len(users)})
    return t, users


def seed_rules(db: Session, t: Tenant, users: dict[str, User]) -> None:
    drafter, approver = users["legal"], users["legal2"]
    versions: dict[str, int] = {}
    for spec in LEGAL_RULES:
        v = versions[spec["rule_code"]] = versions.get(spec["rule_code"], 0) + 1
        r = LegalRule(tenant_id=t.id, version=v, jurisdiction=t.legal_jurisdiction, created_by=drafter.id, **spec)
        db.add(r)
        db.flush()
        audit.record(db, tenant_id=t.id, actor_id=drafter.id, actor_role=drafter.role, action="legal_rule.drafted",
                     resource_type="legal_rule", resource_id=r.id, details={"rule_code": r.rule_code, "version": v})
        obligations.submit_rule(db, r, drafter.id, drafter.role)
        obligations.approve_rule(db, r, approver.id, approver.role, "Seeded demo catalogue — dual approval")


def seed_model(db: Session, t: Tenant, users: dict[str, User]) -> RiskModel:
    m = RiskModel(tenant_id=t.id, version=1, name="Pilot baseline (placeholder weights)", weights=scoring.DEFAULT_WEIGHTS,
                  thresholds=dict(scoring.DEFAULT_THRESHOLDS), created_by=users["analyst"].id,
                  notes="Illustrative weights from PRD §6; not validated policy. Bands pending back-testing.")
    db.add(m)
    db.flush()
    risk_models.submit(db, m, users["analyst"].id, users["analyst"].role)
    risk_models.approve(db, m, users["manager"].id, users["manager"].role, "Approved for shadow-mode pilot runs")
    return m


def load_batches(db: Session, t: Tenant, steward: User, fixture_dir: Path) -> list:
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    out = []
    for b in manifest["batches"]:
        records = json.loads((fixture_dir / b["file"]).read_text())
        batch, _ = ingestion.register_batch(
            db, tenant_id=t.id, user_id=steward.id, dataset=b["dataset"], source_system=b["source_system"],
            schema_version="1.0", idempotency_key=f"seed-{t.state_code}-{b['file']}",
            checksum=ingestion.records_checksum(records), records=records,
            extracted_at=date.fromisoformat(b["extracted_at"]),
        )
        ingestion.process_batch(db, batch.id)
        if b["dataset"] == "taxpayers":
            entity_resolution.find_candidates(db, t.id)
        out.append(batch)
    return out


def run_risk(db: Session, t: Tenant, model: RiskModel, user: User, tax_type: str, period: str) -> RiskRun:
    run = RiskRun(tenant_id=t.id, model_id=model.id, model_version=model.version, engine_version=scoring.ENGINE_VERSION,
                  tax_type=tax_type, period=period, as_of=today(), requested_by=user.id)
    db.add(run)
    db.flush()
    return scoring.execute_run(db, run.id)


def demo_workflow(db: Session, t: Tenant, users: dict[str, User]) -> None:
    """Walk representative alerts through Journeys A–C so outcome metrics are populated."""
    analyst, manager, manager2, officer, auditor = (users[k] for k in ("analyst", "manager", "manager2", "officer", "audit"))
    alerts = db.execute(
        select(Alert).where(Alert.tenant_id == t.id, Alert.status == "open", Alert.tax_type == "PAYE").order_by(Alert.priority.desc())
    ).scalars().all()
    if len(alerts) < 4:
        return
    perms = lambda u: permissions_for(u.role)  # noqa: E731

    # Journey A+B: confirm → case → reminder approved → worked → closed with collection
    a = alerts[0]
    cases.triage(db, a, "confirm", "Evidence reviewed: deadlines passed and feeds fresh", analyst.id, analyst.role)
    c = cases.create_case(db, a, analyst.id, analyst.role, "Confirmed non-filing pattern across several months")
    cases.apply_action(db, c, "submit_proposal", user_id=analyst.id, role=analyst.role, perms=perms(analyst),
                       justification="Proportionate first step: filing reminder", payload={"intervention_type": "filing_reminder"})
    cases.apply_action(db, c, "approve_proposal", user_id=manager.id, role=manager.role, perms=perms(manager),
                       justification="Evidence sufficient; reminder is proportionate", payload={"assignee_id": str(officer.id)})
    cases.apply_action(db, c, "start_work", user_id=officer.id, role=officer.role, perms=perms(officer),
                       justification="Reminder letter issued via approved template", payload={})
    cases.apply_action(db, c, "record_contact", user_id=officer.id, role=officer.role, perms=perms(officer),
                       justification="Spoke to payroll officer; outstanding returns promised", payload={"channel": "phone"})
    cases.apply_action(db, c, "close", user_id=manager.id, role=manager.role, perms=perms(manager),
                       justification="Returns filed and arrears paid", payload={"disposition": "resolved_collected",
                                                                                 "amount_collected": "1250000.00"})

    # Journey C: escalate → case → audit referral → rejected by audit manager → back to review
    b = alerts[1]
    cases.triage(db, b, "escalate", "Large shortfall; needs manager review", analyst.id, analyst.role)
    c2 = cases.create_case(db, b, manager.id, manager.role, "Escalated shortfall case")
    cases.apply_action(db, c2, "refer_audit", user_id=manager.id, role=manager.role, perms=perms(manager),
                       justification="Material shortfall over multiple periods",
                       payload={"intervention_type": "audit_referral", "materiality": "Exposure exceeds desk-review threshold"})
    cases.apply_action(db, c2, "reject_audit", user_id=auditor.id, role=auditor.role, perms=perms(auditor),
                       justification="Insufficient audit capacity this quarter; try payment follow-up first", payload={})

    # Pending approval in the manager queue
    d = alerts[2]
    cases.triage(db, d, "confirm", "Underpayment confirmed against receipts", analyst.id, analyst.role)
    c3 = cases.create_case(db, d, analyst.id, analyst.role, "Underpayment case")
    cases.apply_action(db, c3, "submit_proposal", user_id=analyst.id, role=analyst.role, perms=perms(analyst),
                       justification="Approved payment follow-up recommended", payload={"intervention_type": "payment_follow_up"})

    # Dismissal with reason
    e = alerts[3]
    cases.triage(db, e, "dismiss", "Known payroll system migration; returns filed on paper", manager2.id, manager2.role)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="Drop and recreate all tables (destroys data)")
    ap.add_argument("--no-workflow", action="store_true")
    ap.add_argument("--fixtures", default=str(FIXTURE_DIR))
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args(argv)
    engine = dbmod.configure(args.database_url)
    if args.reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with dbmod.session_factory()() as db:
        if db.execute(select(Tenant).where(Tenant.state_code == "NI")).first():
            print("Already seeded (use --reset to rebuild).")
            return
        t, users = create_tenant(db, "NI", "Niger State Internal Revenue Service", "niger.taxcris.test")
        seed_rules(db, t, users)
        model = seed_model(db, t, users)
        load_batches(db, t, users["steward"], Path(args.fixtures))
        for tax_type, period in (("PAYE", "2026"), ("DA", "2025")):
            run_risk(db, t, model, users["analyst"], tax_type, period)
        if not args.no_workflow:
            demo_workflow(db, t, users)
        # Second tenant: same catalogue, tiny dataset — used to demonstrate isolation.
        k, kusers = create_tenant(db, "KW", "Kwara State Internal Revenue Service", "kwara.taxcris.test")
        seed_rules(db, k, kusers)
        seed_model(db, k, kusers)
        db.commit()
        print(f"Seeded tenants NI and KW. Log in as e.g. analyst@niger.taxcris.test / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
