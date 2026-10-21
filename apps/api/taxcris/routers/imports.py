import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .. import jobs
from ..deps import DB, Principal, require
from ..domain import ingestion
from ..models import ImportBatch, ImportRecord, Job
from ..permissions import P
from ..schemas import ImportIn, ImportOut, ImportRecordOut, Page
from ._common import Limit, Offset, get_scoped, paginate

router = APIRouter(prefix="/v1", tags=["ingestion"])


def _out(batch: ImportBatch, db) -> ImportOut:
    return ImportOut.model_validate(batch)


@router.post("/imports", response_model=ImportOut, status_code=202, summary="Register an ingestion batch")
def create_import(body: ImportIn, db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_CREATE))]) -> ImportOut:
    """Lands raw records immutably, then validates asynchronously. Re-sending the same
    ``idempotency_key`` with the same checksum returns the original batch."""
    try:
        batch, created = ingestion.register_batch(
            db, tenant_id=principal.tenant_id, user_id=principal.user_id, dataset=body.dataset,
            source_system=body.source_system, schema_version=body.schema_version, idempotency_key=body.idempotency_key,
            checksum=body.checksum, records=body.records, extracted_at=body.extracted_at,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409 if "Idempotency" in str(exc) else 422, str(exc))
    job = jobs.enqueue(db, principal.tenant_id, "import.process", {"batch_id": str(batch.id)}) if created else None
    if job is not None:
        batch.job_id = job.id
    db.commit()
    if job is not None:
        jobs.dispatch(job)
        db.refresh(batch)
    return _out(batch, db)


@router.get("/imports", response_model=Page[ImportOut])
def list_imports(db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_READ))],
                 dataset: str | None = None, limit: int = Limit, offset: int = Offset) -> Page[ImportOut]:
    q = select(ImportBatch).where(ImportBatch.tenant_id == principal.tenant_id).order_by(ImportBatch.created_at.desc())
    if dataset:
        q = q.where(ImportBatch.dataset == dataset)
    rows, total = paginate(db, q, limit, offset)
    return Page(items=[ImportOut.model_validate(r[0]) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/imports/{batch_id}", response_model=ImportOut)
def get_import(batch_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_READ))]) -> ImportOut:
    return _out(get_scoped(db, ImportBatch, batch_id, principal), db)


@router.get("/imports/{batch_id}/records", response_model=Page[ImportRecordOut])
def import_records(batch_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_READ))],
                   status: str | None = None, limit: int = Limit, offset: int = Offset) -> Page[ImportRecordOut]:
    get_scoped(db, ImportBatch, batch_id, principal)
    q = select(ImportRecord).where(ImportRecord.batch_id == batch_id).order_by(ImportRecord.row_number)
    if status:
        q = q.where(ImportRecord.status == status)
    rows, total = paginate(db, q, limit, offset)
    return Page(items=[ImportRecordOut.model_validate(r[0]) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/import-records/{record_id}/reprocess", response_model=ImportRecordOut)
def reprocess(record_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.DATA_QUALITY_REVIEW))]) -> ImportRecord:
    get_scoped(db, ImportRecord, record_id, principal)
    try:
        rec = ingestion.reprocess_quarantined(db, principal.tenant_id, principal.user_id, record_id)
    except LookupError:
        raise HTTPException(409, "Record is not quarantined")
    db.commit()
    return rec


@router.get("/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: uuid.UUID, db: DB, principal: Annotated[Principal, Depends(require(P.IMPORTS_READ))]) -> dict:
    job = get_scoped(db, Job, job_id, principal)
    return {"id": job.id, "kind": job.kind, "status": job.status, "attempts": job.attempts, "error": job.error,
            "created_at": job.created_at, "finished_at": job.finished_at}
