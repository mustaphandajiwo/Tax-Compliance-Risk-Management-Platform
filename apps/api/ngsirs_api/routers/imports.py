from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from importer import FEEDS

from .. import audit
from ..errors import not_found, unprocessable
from ..idempotency import run_once
from ..models import DataSource, IdentityMatch, IngestBatch, SourceRecord
from ..schemas import IdentityDecision, ImportBatchOut, QuarantineResolution, RollbackRequest
from ..security.auth import Principal, declared_purpose, get_db, require
from ..services import identity, imports
from ..services.analytics import source_freshness

router = APIRouter(prefix="/api/v1", tags=["imports & data quality"])
MAX_UPLOAD = 50 * 1024 * 1024


def _source_names(db: Session) -> dict:
    return {s.id: s.source_name for s in db.execute(select(DataSource)).scalars()}


@router.get("/imports/templates")
def templates(_: Principal = Depends(require("imports:read"))) -> list[dict]:
    return [
        {
            "feed_type": f.feed_type,
            "title": f.title,
            "description": f.description,
            "safeguard": f.safeguard,
            "natural_key": list(f.natural_key),
            "columns": [
                {
                    "name": c.name,
                    "type": c.type,
                    "required": c.required,
                    "values": list(c.values),
                    "description": c.description,
                }
                for c in f.columns
            ],
        }
        for f in FEEDS.values()
    ]


@router.get("/data-sources")
def data_sources(
    _: Principal = Depends(require("imports:read")), db: Session = Depends(get_db)
) -> list[dict]:
    fresh = {(r["source"], r["feed_type"]): r for r in source_freshness(db)}
    return [
        {
            "id": str(s.id),
            "source_name": s.source_name,
            "feed_types": s.feed_types,
            "system_of_record": s.system_of_record,
            "data_sharing_basis": s.data_sharing_basis,
            "owner": s.owner,
            "permitted_purpose": s.permitted_purpose,
            "freshness_sla_days": s.freshness_sla_days,
            "is_external": s.is_external,
            "enabled": s.enabled,
            "freshness": [fresh.get((s.source_name, f)) for f in s.feed_types],
        }
        for s in db.execute(select(DataSource).order_by(DataSource.source_name)).scalars()
    ]


@router.post("/imports", response_model=ImportBatchOut, status_code=201)
async def create_import(
    file: UploadFile = File(...),
    source: str = Form(...),
    feed_type: str = Form(...),
    extracted_at: datetime = Form(...),
    coverage_from: str | None = Form(None),
    coverage_to: str | None = Form(None),
    coverage_lga: str | None = Form(None),
    field_mapping: str | None = Form(None, description="JSON object: source column -> canonical column"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require("imports:create")),
    db: Session = Depends(get_db),
) -> dict:
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        raise unprocessable("File exceeds 50 MB upload limit")
    mapping = None
    if field_mapping:
        try:
            mapping = json.loads(field_mapping)
            assert isinstance(mapping, dict)
        except Exception:
            raise unprocessable("field_mapping must be a JSON object") from None

    def do() -> dict:
        batch, created = imports.create_batch(
            db,
            principal,
            source_name=source,
            feed_type=feed_type,
            file_name=file.filename or "upload.csv",
            content=content,
            extracted_at=extracted_at,
            coverage_from=coverage_from,
            coverage_to=coverage_to,
            coverage_lga=coverage_lga,
            mapping=mapping,
        )
        return {**imports.batch_payload(batch, source), "created": created}

    return run_once(
        db,
        principal,
        idempotency_key,
        "POST /imports",  # type: ignore[no-any-return]
        {"source": source, "feed": feed_type, "size": len(content), "name": file.filename},
        do,
    )


@router.get("/imports", response_model=list[ImportBatchOut])
def list_imports(
    feed_type: str | None = None,
    status: str | None = None,
    _: Principal = Depends(require("imports:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(IngestBatch).order_by(IngestBatch.seq.desc())
    if feed_type:
        q = q.where(IngestBatch.feed_type == feed_type)
    if status:
        q = q.where(IngestBatch.qa_status == status)
    names = _source_names(db)
    return [imports.batch_payload(b, names.get(b.source_id)) for b in db.execute(q.limit(200)).scalars()]


def _batch(db: Session, batch_id: uuid.UUID) -> IngestBatch:
    b = db.get(IngestBatch, batch_id)
    if b is None:
        raise not_found("Import batch")
    return b


@router.get("/imports/{batch_id}", response_model=ImportBatchOut)
def get_import(
    batch_id: uuid.UUID, _: Principal = Depends(require("imports:read")), db: Session = Depends(get_db)
) -> dict:
    b = _batch(db, batch_id)
    return imports.batch_payload(b, _source_names(db).get(b.source_id))


@router.get("/imports/{batch_id}/quality")
def import_quality(
    batch_id: uuid.UUID, _: Principal = Depends(require("imports:read")), db: Session = Depends(get_db)
) -> dict:
    b = _batch(db, batch_id)
    return {"batch_id": str(b.id), "qa_status": b.qa_status, **b.quality_report}


@router.get("/imports/{batch_id}/rows")
def import_rows(
    batch_id: uuid.UUID,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _: Principal = Depends(require("imports:read")),
    db: Session = Depends(get_db),
) -> dict:
    _batch(db, batch_id)
    q = select(SourceRecord).where(SourceRecord.batch_id == batch_id)
    if status:
        q = q.where(SourceRecord.status == status)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(SourceRecord.row_number).offset((page - 1) * page_size).limit(page_size)
    ).scalars()
    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": str(r.id),
                "row_number": r.row_number,
                "status": r.status,
                "natural_id": r.natural_id,
                "reasons": r.reason_codes,
                "messages": r.messages,
                "raw": r.raw,
                "resolution": r.resolution,
            }
            for r in rows
        ],
    }


@router.post("/imports/{batch_id}/commit", response_model=ImportBatchOut)
def commit_import(
    batch_id: uuid.UUID,
    principal: Principal = Depends(require("imports:commit")),
    db: Session = Depends(get_db),
) -> dict:
    b = imports.commit_batch(db, principal, batch_id)
    return imports.batch_payload(b, _source_names(db).get(b.source_id))


@router.post("/imports/{batch_id}/rollback", response_model=ImportBatchOut)
def rollback_import(
    batch_id: uuid.UUID,
    body: RollbackRequest,
    principal: Principal = Depends(require("imports:rollback")),
    db: Session = Depends(get_db),
) -> dict:
    b = imports.rollback_batch(db, principal, batch_id, body.reason)
    return imports.batch_payload(b, _source_names(db).get(b.source_id))


@router.get("/data-quality/quarantine")
def quarantine(
    reason: str | None = None,
    include_resolved: bool = False,
    _: Principal = Depends(require("quality:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(SourceRecord).where(SourceRecord.status == "quarantined")
    if not include_resolved:
        q = q.where(SourceRecord.resolution.is_(None) | (SourceRecord.resolution == "escalated"))
    if reason:
        q = q.where(SourceRecord.reason_codes.any(reason))
    batches = {b.id: b for b in db.execute(select(IngestBatch)).scalars()}
    out = []
    for r in db.execute(q.order_by(SourceRecord.feed_type, SourceRecord.row_number).limit(500)).scalars():
        b = batches.get(r.batch_id)
        out.append(
            {
                "id": str(r.id),
                "feed_type": r.feed_type,
                "batch_id": str(r.batch_id),
                "batch_seq": b.seq if b else None,
                "row_number": r.row_number,
                "natural_id": r.natural_id,
                "employer_ref": r.employer_ref,
                "reasons": r.reason_codes,
                "messages": r.messages,
                "raw": r.raw,
                "resolution": r.resolution,
                "resolved_by": r.resolved_by,
            }
        )
    return out


@router.post("/data-quality/quarantine/{record_id}/resolve")
def resolve_quarantine(
    record_id: uuid.UUID,
    body: QuarantineResolution,
    principal: Principal = Depends(require("quality:resolve")),
    db: Session = Depends(get_db),
) -> dict:
    r = imports.resolve_quarantine(db, principal, record_id, body.resolution, body.note)
    return {"id": str(r.id), "resolution": r.resolution, "resolved_by": r.resolved_by}


@router.get("/identity-matches")
def identity_matches(
    status: str | None = "pending_review",
    principal: Principal = Depends(require("quality:read")),
    purpose: str | None = Header(default=None, alias="X-Purpose"),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(IdentityMatch).order_by(IdentityMatch.created_at.desc())
    if status:
        q = q.where(IdentityMatch.status == status)
    from ..models import Employer, Taxpayer

    taxpayers = {t.id: t for t in db.execute(select(Taxpayer)).scalars()}
    employers = {e.id: e for e in db.execute(select(Employer)).scalars()}
    latest = identity.latest_matches(db)
    out = []
    for m in db.execute(q.limit(500)).scalars():
        ref = (m.method_detail or {}).get("employer_ref")
        if latest.get(ref) is not m:
            continue
        emp = employers.get(m.employer_id) if m.employer_id else None
        tp = taxpayers.get(m.taxpayer_id) if m.taxpayer_id else None
        out.append(
            {
                "id": str(m.id),
                "employer_ref": ref,
                "employer_name": emp.display_name if emp else None,
                "employer_lga": emp.lga_code if emp else None,
                "candidate_taxpayer": tp.source_taxpayer_id if tp else None,
                "candidate_name": tp.display_name if tp else None,
                "match_type": m.match_type,
                "confidence": m.confidence,
                "status": m.status,
                "method": m.method_detail,
                "reviewer": m.reviewer,
                "reason": m.reason,
            }
        )
    if purpose:
        declared_purpose(principal, purpose)
        audit.record(
            db, principal, "identity.queue_viewed", "identity_matches", {"count": len(out)}, purpose=purpose
        )
    return out


@router.post("/identity-matches/{match_id}/decision")
def identity_decision(
    match_id: uuid.UUID,
    body: IdentityDecision,
    principal: Principal = Depends(require("identity:review")),
    db: Session = Depends(get_db),
) -> dict:
    return identity.decide(db, principal, match_id, body.decision, body.reason)
