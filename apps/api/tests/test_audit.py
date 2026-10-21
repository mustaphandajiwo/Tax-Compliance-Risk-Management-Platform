"""Tamper-evident audit trail."""

from sqlalchemy import select, update

from taxcris import db as dbmod
from taxcris.audit import verify_chain
from taxcris.models import AuditEvent


def test_chain_verifies_and_detects_tampering(env):
    env.client.get("/v1/legal-rules", headers=env.h("legal"))
    r = env.client.get("/v1/audit-events/verify", headers=env.h("security"))
    assert r.json()["valid"] is True and r.json()["events_checked"] > 5

    tenant_id = env.tenants["NI"].id
    with dbmod.session_factory()() as db:
        ev = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.seq == 3)).scalar_one()
        db.execute(update(AuditEvent).where(AuditEvent.id == ev.id).values(details={"reason": "rewritten"}))
        db.commit()
        res = verify_chain(db, tenant_id)
    assert res["valid"] is False and res["first_invalid_seq"] == 3


def test_deletion_is_detected(env):
    tenant_id = env.tenants["NI"].id
    with dbmod.session_factory()() as db:
        last = db.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.seq.desc())).scalars().first()
        db.delete(last)
        db.commit()
        assert verify_chain(db, tenant_id)["valid"] is False


def test_chains_are_per_tenant(env):
    with dbmod.session_factory()() as db:
        assert verify_chain(db, env.tenants["KW"].id)["valid"]
