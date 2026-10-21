"""Data reconciliation: every record accounted for; idempotency; quarantine; entity resolution."""

from taxcris.domain.ingestion import records_checksum
from taxcris.testing import load_small, small_dataset, taxpayer_id


def test_batch_reconciles_with_rejected_duplicate_and_quarantined(env):
    load_small(env)
    good = small_dataset()["returns"][0]
    records = [
        {**good, "source_record_id": "NEW-1", "period": "2026-13"},       # rejected: bad period
        {**good, "source_record_id": "NEW-2", "reported_amount": "-1"},    # rejected: negative
        good,                                                               # duplicate: already ingested
        {**good, "source_record_id": "NEW-3", "tin": "SYN-UNKNOWN"},       # quarantined: unknown TIN
        {**good, "source_record_id": "NEW-4", "period": "2025-01"},       # accepted
        {**good, "source_record_id": "NEW-4", "period": "2025-01"},       # duplicate within batch
    ]
    b = env.import_records("returns", records).json()
    assert (b["total"], b["accepted"], b["rejected"], b["duplicate"], b["quarantined"]) == (6, 1, 2, 2, 1)
    assert b["reconciliation_status"] == "reconciled" and b["status"] == "completed"
    rej = env.client.get(f"/v1/imports/{b['id']}/records", params={"status": "rejected"}, headers=env.h("steward")).json()
    assert {e["field"] for r in rej["items"] for e in r["errors"]} == {"period", "reported_amount"}


def test_idempotent_resubmission_and_checksum_guards(env):
    recs = small_dataset()["taxpayers"]
    first = env.import_records("taxpayers", recs, key="same-key-123")
    again = env.import_records("taxpayers", recs, key="same-key-123")
    assert first.json()["id"] == again.json()["id"]
    other = env.import_records("taxpayers", recs[:2], key="same-key-123")
    assert other.status_code == 409
    bad = env.client.post("/v1/imports", headers=env.h("steward"), json={
        "dataset": "taxpayers", "source_system": "X", "idempotency_key": "another-key", "checksum": "0" * 64,
        "records": recs})
    assert bad.status_code == 422


def test_checksum_is_canonical_json_sha256():
    assert records_checksum([{"b": 1, "a": "x"}]) == records_checksum([{"a": "x", "b": 1}])


def test_quarantined_record_can_be_reprocessed_after_registration(env):
    good = small_dataset()["returns"][0]
    b = env.import_records("returns", [{**good, "tin": "SYN-LATE-REG"}]).json()
    assert b["quarantined"] == 1
    env.import_records("taxpayers", [{"source_record_id": "LR", "taxpayer_type": "business", "name": "Late Reg Ltd",
                                      "tin": "SYN-LATE-REG", "tax_residence": "NI", "is_employer": True}])
    q = env.client.get("/v1/data-quality/quarantine", headers=env.h("steward")).json()["items"][0]
    r = env.client.post(f"/v1/import-records/{q['id']}/reprocess", headers=env.h("steward"))
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert env.client.get(f"/v1/imports/{b['id']}", headers=env.h("steward")).json()["accepted"] == 1


def test_identifiers_are_hashed_and_masked(env):
    load_small(env)
    tid = taxpayer_id(env, "Kpada")
    analyst_view = env.client.get(f"/v1/taxpayers/{tid}", headers=env.h("analyst")).json()
    values = [i["value"] for i in analyst_view["identifiers"]]
    assert values == ["********0001"] and "SYN-T0000001" not in str(analyst_view)


def test_duplicate_merge_requires_two_stewards_and_can_roll_back(env):
    load_small(env)
    dup = dict(small_dataset()["taxpayers"][0], source_record_id="LEGACY-1", name="KPADA FRESH FARMS NIG LTD")
    env.import_records("taxpayers", [dup], source="LEGACY")
    cands = env.client.get("/v1/merge-candidates", headers=env.h("steward")).json()["items"]
    assert len(cands) == 1 and "shared_tin" in cands[0]["reasons"] and cands[0]["confidence"] >= 0.9
    cid = cands[0]["id"]
    assert env.client.post(f"/v1/merge-candidates/{cid}/decision", json={"decision": "propose", "reason": "Same TIN"},
                           headers=env.h("steward")).status_code == 200
    self_approve = env.client.post(f"/v1/merge-candidates/{cid}/decision", json={"decision": "approve", "reason": "ok ok"},
                                   headers=env.h("steward"))
    assert self_approve.status_code == 403
    ok = env.client.post(f"/v1/merge-candidates/{cid}/decision", json={"decision": "approve", "reason": "Verified"},
                         headers=env.h("steward2"))
    assert ok.status_code == 200 and ok.json()["status"] == "merged"
    names = [t["name"] for t in env.client.get("/v1/taxpayers", params={"q": "kpada"}, headers=env.h("analyst")).json()["items"]]
    assert names == ["Kpada Fresh Farms Ltd"]
    rb = env.client.post(f"/v1/merge-candidates/{cid}/decision", json={"decision": "rollback", "reason": "Wrong merge"},
                         headers=env.h("steward2"))
    assert rb.json()["status"] == "rolled_back"
    assert env.client.get("/v1/taxpayers", params={"q": "kpada"}, headers=env.h("analyst")).json()["total"] == 2
