"""Ingestion pipeline (FR-01, PRD §13).

Every submitted record lands immutably in ``import_records`` and ends in exactly one of
accepted / rejected / duplicate / quarantined, so a batch always reconciles:
``total == accepted + rejected + duplicate + quarantined`` (no silent loss).

* rejected    — fails schema validation
* duplicate   — same source record already ingested (by source_system + source_record_id)
* quarantined — valid shape, but cannot be safely linked (e.g. unknown taxpayer TIN); a data
                steward resolves it in the data-quality workbench
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import today
from ..models import Employment, IdentityLink, ImportBatch, ImportRecord, Payment, Taxpayer, TaxReturn, Tenant
from ..security import hash_identifier, mask_identifier, sha256_json

PERIOD_PATTERN = r"^\d{4}(-(0[1-9]|1[0-2]))?$"


class TaxpayerIn(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=120)
    taxpayer_type: Literal["individual", "business"]
    name: str = Field(min_length=2, max_length=250)
    tin: str | None = Field(default=None, min_length=6, max_length=30)
    nin: str | None = Field(default=None, min_length=6, max_length=30)
    cac_rc: str | None = Field(default=None, min_length=3, max_length=30)
    registration_status: Literal["registered", "unregistered", "deregistered"] = "registered"
    tax_residence: str = Field(min_length=2, max_length=8)
    lga: str | None = None
    sector: str | None = None
    is_employer: bool = False
    self_employed: bool = False
    operating_status: Literal["active", "dormant", "closed"] = "active"
    closed_on: date | None = None
    registered_on: date | None = None


class EmploymentIn(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=120)
    employer_tin: str
    employee_tin: str
    start_date: date
    end_date: date | None = None
    monthly_gross: Decimal | None = Field(default=None, ge=0)


class ReturnIn(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=120)
    tin: str
    tax_type: Literal["PAYE", "DA"]
    period: str = Field(pattern=PERIOD_PATTERN)
    filing_date: date
    reported_income: Decimal = Field(ge=0)
    reported_amount: Decimal = Field(ge=0)
    employee_count: int | None = Field(default=None, ge=0)


class PaymentIn(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=120)
    tin: str
    tax_type: Literal["PAYE", "DA"]
    period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    amount: Decimal = Field(gt=0)
    payment_date: date
    allocation_status: Literal["allocated", "unallocated", "disputed"] = "allocated"
    channel: str | None = None

    @field_validator("payment_date")
    @classmethod
    def not_future(cls, v: date) -> date:
        if v > today():
            raise ValueError("payment_date is in the future")
        return v


DATASETS: dict[str, type[BaseModel]] = {
    "taxpayers": TaxpayerIn,
    "employments": EmploymentIn,
    "returns": ReturnIn,
    "payments": PaymentIn,
}
TARGET_MODEL = {"taxpayers": Taxpayer, "employments": Employment, "returns": TaxReturn, "payments": Payment}


def records_checksum(records: list[dict]) -> str:
    return sha256_json(records)


def register_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    dataset: str,
    source_system: str,
    schema_version: str,
    idempotency_key: str,
    checksum: str,
    records: list[dict],
    extracted_at: date | None = None,
) -> tuple[ImportBatch, bool]:
    """Land raw records and return (batch, created). Re-submitting the same key is a no-op."""
    existing = db.execute(
        select(ImportBatch).where(ImportBatch.tenant_id == tenant_id, ImportBatch.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.checksum != checksum:
            raise ValueError("Idempotency key reused with a different payload checksum")
        return existing, False
    if records_checksum(records) != checksum:
        raise ValueError("Checksum does not match submitted records")
    batch = ImportBatch(
        tenant_id=tenant_id,
        dataset=dataset,
        source_system=source_system,
        schema_version=schema_version,
        idempotency_key=idempotency_key,
        checksum=checksum,
        extracted_at=extracted_at or today(),
        total=len(records),
        submitted_by=user_id,
    )
    db.add(batch)
    db.flush()
    for i, raw in enumerate(records, start=1):
        db.add(
            ImportRecord(
                tenant_id=tenant_id,
                batch_id=batch.id,
                row_number=i,
                raw=raw,
                raw_hash=sha256_json(raw),
                source_record_id=str(raw.get("source_record_id")) if isinstance(raw, dict) and raw.get("source_record_id") else None,
                status="pending",
            )
        )
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="import.registered",
        resource_type="import_batch",
        resource_id=batch.id,
        details={"dataset": dataset, "source_system": source_system, "total": len(records), "checksum": checksum},
    )
    db.flush()
    return batch, True


class _Resolver:
    def __init__(self, db: Session, tenant: Tenant):
        self.db = db
        self.tenant = tenant
        self._cache: dict[str, uuid.UUID | None] = {}

    def by_tin(self, tin: str) -> uuid.UUID | None:
        h = hash_identifier(self.tenant.identifier_salt, "TIN", tin)
        if h in self._cache:
            return self._cache[h]
        link = self.db.execute(
            select(IdentityLink)
            .where(
                IdentityLink.tenant_id == self.tenant.id,
                IdentityLink.identifier_type == "TIN",
                IdentityLink.hashed_identifier == h,
            )
            .order_by(IdentityLink.match_confidence.desc(), IdentityLink.created_at)
        ).scalars().first()
        tid = None
        if link is not None:
            tid = link.taxpayer_id
            # Follow merges to the surviving record.
            seen = set()
            while tid not in seen:
                seen.add(tid)
                tp = self.db.get(Taxpayer, tid)
                if tp is None or tp.merged_into_id is None:
                    break
                tid = tp.merged_into_id
        self._cache[h] = tid
        return tid

    def invalidate(self, tin: str) -> None:
        self._cache.pop(hash_identifier(self.tenant.identifier_salt, "TIN", tin), None)


def _exists(db: Session, model, tenant_id: uuid.UUID, source_system: str, source_record_id: str) -> bool:
    return (
        db.execute(
            select(model.id).where(
                model.tenant_id == tenant_id,
                model.source_system == source_system,
                model.source_record_id == source_record_id,
            )
        ).first()
        is not None
    )


def process_batch(db: Session, batch_id: uuid.UUID) -> ImportBatch:
    """Validate and normalise a landed batch. Idempotent: already-processed rows are skipped."""
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise LookupError(batch_id)
    tenant = db.get(Tenant, batch.tenant_id)
    schema = DATASETS[batch.dataset]
    resolver = _Resolver(db, tenant)
    batch.status = "validating"
    seen_in_batch: set[str] = set()

    rows = db.execute(
        select(ImportRecord).where(ImportRecord.batch_id == batch.id).order_by(ImportRecord.row_number)
    ).scalars()
    for rec in rows:
        if rec.status != "pending":
            continue
        try:
            item = schema.model_validate(rec.raw)
        except ValidationError as exc:
            rec.status = "rejected"
            rec.errors = [
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in exc.errors()
            ]
            continue
        sid = item.source_record_id
        if sid in seen_in_batch or _exists(db, TARGET_MODEL[batch.dataset], tenant.id, batch.source_system, sid):
            rec.status = "duplicate"
            rec.errors = [{"field": "source_record_id", "message": "Record already ingested from this source"}]
            continue
        seen_in_batch.add(sid)
        handler = _HANDLERS[batch.dataset]
        handler(db, tenant, batch, rec, item, resolver)

    db.flush()
    counts = {"accepted": 0, "rejected": 0, "duplicate": 0, "quarantined": 0}
    for (st,) in db.execute(select(ImportRecord.status).where(ImportRecord.batch_id == batch.id)):
        counts[st] = counts.get(st, 0) + 1
    batch.accepted, batch.rejected = counts["accepted"], counts["rejected"]
    batch.duplicate, batch.quarantined = counts["duplicate"], counts["quarantined"]
    accounted = batch.accepted + batch.rejected + batch.duplicate + batch.quarantined
    batch.reconciliation_status = "reconciled" if accounted == batch.total else "unreconciled"
    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)
    audit.record(
        db,
        tenant_id=tenant.id,
        actor_id=batch.submitted_by,
        action="import.completed",
        resource_type="import_batch",
        resource_id=batch.id,
        details={**counts, "total": batch.total, "reconciliation": batch.reconciliation_status},
    )
    db.flush()
    return batch


def _add_link(db: Session, tenant: Tenant, taxpayer_id: uuid.UUID, id_type: str, value: str, source_ref: str) -> None:
    db.add(
        IdentityLink(
            tenant_id=tenant.id,
            taxpayer_id=taxpayer_id,
            identifier_type=id_type,
            hashed_identifier=hash_identifier(tenant.identifier_salt, id_type, value),
            masked_value=mask_identifier(value),
            match_confidence=1.0,
            source_ref=source_ref,
        )
    )


def _handle_taxpayer(db, tenant, batch, rec, item: TaxpayerIn, resolver: _Resolver) -> None:
    tp = Taxpayer(
        tenant_id=tenant.id,
        taxpayer_type=item.taxpayer_type,
        name=item.name.strip(),
        registration_status=item.registration_status,
        tax_residence=item.tax_residence.upper(),
        lga=item.lga,
        sector=item.sector,
        is_employer=item.is_employer,
        self_employed=item.self_employed,
        operating_status=item.operating_status,
        closed_on=item.closed_on,
        registered_on=item.registered_on,
        source_system=batch.source_system,
        source_record_id=item.source_record_id,
        source_batch_id=batch.id,
    )
    db.add(tp)
    db.flush()
    ref = f"{batch.source_system}:{item.source_record_id}"
    for id_type, value in (("TIN", item.tin), ("NIN", item.nin), ("CAC_RC", item.cac_rc)):
        if value:
            _add_link(db, tenant, tp.id, id_type, value, ref)
            if id_type == "TIN":
                resolver.invalidate(value)
    rec.status, rec.target_type, rec.target_id = "accepted", "taxpayer", tp.id


def _quarantine(rec, message: str, field: str = "tin") -> None:
    rec.status = "quarantined"
    rec.errors = [{"field": field, "message": message}]


def _handle_employment(db, tenant, batch, rec, item: EmploymentIn, resolver: _Resolver) -> None:
    employer, employee = resolver.by_tin(item.employer_tin), resolver.by_tin(item.employee_tin)
    if employer is None or employee is None:
        _quarantine(rec, "Employer or employee TIN not found in taxpayer master")
        return
    emp = Employment(
        tenant_id=tenant.id,
        employer_id=employer,
        employee_id=employee,
        start_date=item.start_date,
        end_date=item.end_date,
        monthly_gross=item.monthly_gross,
        source_system=batch.source_system,
        source_record_id=item.source_record_id,
    )
    db.add(emp)
    db.flush()
    rec.status, rec.target_type, rec.target_id = "accepted", "employment", emp.id


def _handle_return(db, tenant, batch, rec, item: ReturnIn, resolver: _Resolver) -> None:
    tid = resolver.by_tin(item.tin)
    if tid is None:
        _quarantine(rec, "TIN not found in taxpayer master")
        return
    r = TaxReturn(
        tenant_id=tenant.id,
        taxpayer_id=tid,
        tax_type=item.tax_type,
        period=item.period,
        filing_date=item.filing_date,
        reported_income=item.reported_income,
        reported_amount=item.reported_amount,
        employee_count=item.employee_count,
        source_system=batch.source_system,
        source_record_id=item.source_record_id,
        source_batch_id=batch.id,
    )
    db.add(r)
    db.flush()
    rec.status, rec.target_type, rec.target_id = "accepted", "return", r.id


def _handle_payment(db, tenant, batch, rec, item: PaymentIn, resolver: _Resolver) -> None:
    tid = resolver.by_tin(item.tin)
    if tid is None:
        _quarantine(rec, "TIN not found in taxpayer master")
        return
    p = Payment(
        tenant_id=tenant.id,
        taxpayer_id=tid,
        tax_type=item.tax_type,
        period=item.period,
        amount=item.amount,
        payment_date=item.payment_date,
        allocation_status=item.allocation_status if item.period else "unallocated",
        channel=item.channel,
        source_system=batch.source_system,
        source_record_id=item.source_record_id,
        source_batch_id=batch.id,
    )
    db.add(p)
    db.flush()
    rec.status, rec.target_type, rec.target_id = "accepted", "payment", p.id


_HANDLERS = {
    "taxpayers": _handle_taxpayer,
    "employments": _handle_employment,
    "returns": _handle_return,
    "payments": _handle_payment,
}


def reprocess_quarantined(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, record_id: uuid.UUID) -> ImportRecord:
    """Retry a quarantined row after master data was corrected (e.g. taxpayer now registered)."""
    rec = db.get(ImportRecord, record_id)
    if rec is None or rec.tenant_id != tenant_id or rec.status != "quarantined":
        raise LookupError(record_id)
    batch = db.get(ImportBatch, rec.batch_id)
    tenant = db.get(Tenant, tenant_id)
    item = DATASETS[batch.dataset].model_validate(rec.raw)
    _HANDLERS[batch.dataset](db, tenant, batch, rec, item, _Resolver(db, tenant))
    if rec.status == "accepted":
        rec.resolved_by, rec.resolution = user_id, "reprocessed"
        batch.quarantined -= 1
        batch.accepted += 1
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_id=user_id,
        action="import.record_reprocessed",
        resource_type="import_record",
        resource_id=rec.id,
        details={"result": rec.status},
    )
    return rec
