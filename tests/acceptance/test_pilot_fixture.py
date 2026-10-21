"""Full synthetic Niger pilot fixture: reconciliation and scoring reproducibility at volume."""

import json
from pathlib import Path

from sqlalchemy import select

from taxcris import db as dbmod
from taxcris.domain import scoring
from taxcris.models import ImportBatch, RiskAssessment, RiskModel, RiskRun

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "niger-pilot"


def test_pilot_fixture_reconciles_and_reproduces(env):
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    assert manifest["synthetic"] is True
    for b in manifest["batches"]:
        records = json.loads((FIXTURE / b["file"]).read_text())
        assert all("SYN" in (r.get("tin") or r.get("cac_rc") or r.get("employer_tin") or "SYN") for r in records)
        r = env.import_records(b["dataset"], records, source=b["source_system"], extracted_at=b["extracted_at"])
        out = r.json()
        assert out["reconciliation_status"] == "reconciled"
        assert out["accepted"] + out["rejected"] + out["duplicate"] + out["quarantined"] == len(records)

    for tax_type, period in (("PAYE", "2026"), ("DA", "2025")):
        run = env.client.post("/v1/risk-runs", json={"tax_type": tax_type, "period": period}, headers=env.h("analyst")).json()
        assert run["status"] == "completed" and run["assessed"] > 50 and run["alerts_created"] > 5

    with dbmod.session_factory()() as db:
        assert db.execute(select(ImportBatch).where(ImportBatch.rejected > 0)).first() is not None
        mismatches = 0
        for a in db.execute(select(RiskAssessment)).scalars():
            model = db.get(RiskModel, db.get(RiskRun, a.run_id).model_id)
            mismatches += not scoring.reproduce(a, model)["reproducible"]
        assert mismatches == 0

    # Every planted signal type is exercised
    codes = {c for a in env.client.get("/v1/risk-assessments", params={"limit": 500}, headers=env.h("analyst")).json()["items"]
             for c in a["reason_codes"]}
    assert {"REG-001", "FIL-001", "FIL-002", "PAY-001", "PAY-002", "PAY-003", "REP-001"} <= codes
