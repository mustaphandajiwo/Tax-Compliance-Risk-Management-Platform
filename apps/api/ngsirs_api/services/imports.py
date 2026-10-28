"""Import pipeline: upload -> validate/preview -> commit -> (rollback).

1. ``create_batch`` stores the encrypted original, signs a manifest, parses and
   validates every row into provenance records. Nothing canonical changes yet;
   the batch can be previewed.
2. ``commit_batch`` writes accepted rows into canonical tables. A newer row for
   the same natural key supersedes the current one, it is never edited in place.
3. ``rollback_batch`` reverses a commit exactly, restoring superseded rows.

Re-uploading the same file for the same source and feed returns the existing
batch (idempotent ingestion).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from importer import (
    FEEDS,
    SCHEMA_VERSION,
    ParseError,
    ValidationContext,
    parse_file,
    unmapped_columns,
    validate_rows,
)
from risk_engine.hashing import canonical_json

from .. import audit
from ..errors import bad_request, conflict, forbidden, not_found, unprocessable
from ..models import (
    Assessment,
    DataSource,
    Employer,
    Extension,
    IdentityMatch,
    IngestBatch,
    Lga,
    Payment,
    PaymentAllocation,
    ReturnFiling,
    SourceCoverage,
    SourceRecord,
    TaxObligation,
    Taxpayer,
    TaxpayerIdentifier,
    Tenant,
)
from ..security import crypto
from ..security.auth import Principal
from ..storage import get_store
from . import identity
from .legal import period_range

CANONICAL_MODELS: dict[str, Any] = {
    "ngsirs_taxpayer": Taxpayer,
    "ngsirs_employer": Employer,
    "ngsirs_obligation": TaxObligation,
    "ngsirs_extension": Extension,
    "ngsirs_paye_return": ReturnFiling,
    "ngsirs_payment": Payment,
    "ngsirs_assessment": Assessment,
}
COMMIT_ORDER = [
    "ngsirs_taxpayer",
    "ngsirs_employer",
    "ngsirs_obligation",
    "ngsirs_extension",
    "ngsirs_paye_return",
    "ngsirs_payment",
    "ngsirs_assessment",
]


def current_employer_refs(db: Session) -> set[str]:
    return set(db.execute(select(Employer.source_employer_id).where(Employer.is_current)).scalars())


def create_batch(
    db: Session,
    actor: Principal,
    *,
    source_name: str,
    feed_type: str,
    file_name: str,
    content: bytes,
    extracted_at: datetime,
    coverage_from: str | None,
    coverage_to: str | None,
    coverage_lga: str | None = None,
    mapping: dict[str, str] | None = None,
) -> tuple[IngestBatch, bool]:
    if feed_type not in FEEDS:
        raise unprocessable(f"Unknown feed type {feed_type}", {"known": list(FEEDS)})
    source = db.execute(select(DataSource).where(DataSource.source_name == source_name)).scalar_one_or_none()
    if source is None:
        raise not_found("Data source")
    if not source.enabled:
        raise forbidden("Data source is disabled")
    if feed_type not in source.feed_types:
        raise unprocessable(f"Source {source_name} is not registered for {feed_type}")
    if source.is_external and not source.data_sharing_basis.strip():
        raise forbidden(
            "External import disabled: no authorised legal purpose and data-sharing basis recorded"
        )
    if extracted_at.tzinfo is None:
        raise bad_request("extracted_at must include a timezone")
    if extracted_at > datetime.now(UTC):
        raise unprocessable("extracted_at is in the future")
    if (coverage_from is None) != (coverage_to is None):
        raise unprocessable("coverage_from and coverage_to must be given together")
    if coverage_from and coverage_to and coverage_from > coverage_to:
        raise unprocessable("coverage_from is after coverage_to")

    digest = hashlib.sha256(content).hexdigest()
    existing = db.execute(
        select(IngestBatch).where(
            IngestBatch.source_id == source.id,
            IngestBatch.feed_type == feed_type,
            IngestBatch.content_hash == digest,
            IngestBatch.qa_status != "rolled_back",
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    try:
        headers, rows = parse_file(file_name, content)
    except ParseError as exc:
        raise unprocessable(f"Invalid import file: {exc}") from None

    tenant = db.get(Tenant, actor.tenant_id)
    settings = (tenant.settings if tenant else {}) or {}
    lgas = set(db.execute(select(Lga.code)).scalars())
    ctx = ValidationContext(
        tin_pattern=settings.get("tin_pattern", r"^NGS-DEMO-TIN-\d{6}$"),
        known_lgas=lgas or None,
        known_employers=None
        if feed_type in ("ngsirs_employer", "ngsirs_taxpayer")
        else current_employer_refs(db),
    )
    report = validate_rows(feed_type, headers, rows, mapping, ctx)
    ext = file_name.rsplit(".", 1)[-1].lower()
    object_key = f"{actor.tenant_id}/raw/{feed_type}/{digest}.{ext}"
    get_store().put(object_key, content)

    summary = report.summary()
    staleness = (datetime.now(UTC) - extracted_at).days
    summary["freshness"] = {
        "extracted_at": extracted_at.isoformat(),
        "age_days_at_ingest": staleness,
        "sla_days": source.freshness_sla_days,
        "stale": staleness > source.freshness_sla_days,
    }
    summary["unmapped_columns"] = unmapped_columns(FEEDS[feed_type], headers, mapping or {})
    manifest = {
        "tenant": actor.tenant_code,
        "source": source_name,
        "feed_type": feed_type,
        "file_name": file_name,
        "content_hash": digest,
        "schema_version": SCHEMA_VERSION,
        "extracted_at": extracted_at.isoformat(),
        "coverage": {"from": coverage_from, "to": coverage_to, "lga": coverage_lga},
        "rows": len(rows),
        "uploaded_by": actor.actor_id,
        "uploaded_at": datetime.now(UTC).isoformat(),
        "data_sharing_basis": source.data_sharing_basis,
    }
    batch = IngestBatch(
        tenant_id=actor.tenant_id,
        source_id=source.id,
        feed_type=feed_type,
        schema_version=SCHEMA_VERSION,
        file_name=file_name,
        content_hash=digest,
        object_key=object_key,
        manifest=manifest,
        manifest_signature=crypto.sign(canonical_json(manifest).encode()),
        extracted_at=extracted_at,
        coverage_from=coverage_from,
        coverage_to=coverage_to,
        coverage_lga=coverage_lga,
        qa_status="rejected" if report.rejected_file else "validated",
        row_count=len(rows),
        accepted_count=summary["accepted"],
        quarantined_count=summary["quarantined"],
        rejected_count=summary["rejected"],
        quality_report=summary,
        field_mapping=mapping or {},
        created_by=actor.actor_id,
    )
    db.add(batch)
    db.flush()
    db.add_all(
        [
            SourceRecord(
                tenant_id=actor.tenant_id,
                batch_id=batch.id,
                feed_type=feed_type,
                row_number=r.row_number,
                natural_id=r.natural_id,
                content_hash=r.content_hash,
                raw=r.raw,
                status=r.status,
                reason_codes=r.reasons,
                messages=r.messages,
                employer_ref=r.employer_ref,
            )
            for r in report.results
        ]
    )
    db.flush()
    audit.record(
        db,
        actor,
        "import.batch_created",
        f"batch:{batch.id}",
        {
            "feed_type": feed_type,
            "source": source_name,
            "rows": len(rows),
            "qa_status": batch.qa_status,
            "accepted": summary["accepted"],
            "quarantined": summary["quarantined"],
            "rejected": summary["rejected"],
        },
        after=digest,
    )
    return batch, True


def commit_batch(db: Session, actor: Principal, batch_id: uuid.UUID) -> IngestBatch:
    batch = db.get(IngestBatch, batch_id)
    if batch is None:
        raise not_found("Import batch")
    if batch.qa_status != "validated":
        raise conflict(f"Batch is {batch.qa_status}; only validated batches can be committed")
    source = db.get(DataSource, batch.source_id)
    assert source is not None
    tenant = db.get(Tenant, actor.tenant_id)
    assert tenant is not None
    records = list(
        db.execute(
            select(SourceRecord)
            .where(SourceRecord.batch_id == batch.id, SourceRecord.status == "accepted")
            .order_by(SourceRecord.row_number)
        ).scalars()
    )
    mapping = batch.field_mapping or {}
    feed = batch.feed_type
    model = CANONICAL_MODELS[feed]
    employers = {
        e.source_employer_id: e for e in db.execute(select(Employer).where(Employer.is_current)).scalars()
    }

    def supersede(natural_attr: str, values: list[str]) -> None:
        if not values:
            return
        col = getattr(model, natural_attr)
        db.execute(
            update(model)
            .where(col.in_(values), model.is_current.is_(True))
            .values(is_current=False, superseded_by_batch_id=batch.id)
        )

    rows: list[tuple[SourceRecord, dict[str, Any]]] = []
    for rec in records:
        raw = {mapping.get(k, k): v for k, v in rec.raw.items()}
        rec_values = (
            validate_rows(
                feed,
                list(raw.keys()),
                [raw],
                None,
                ValidationContext(tin_pattern=r".*", known_lgas=None, known_employers=None),
            )
            .results[0]
            .values
        )
        rows.append((rec, rec_values))

    common = {"tenant_id": actor.tenant_id, "batch_id": batch.id}
    if feed == "ngsirs_taxpayer":
        supersede("source_taxpayer_id", [v["source_taxpayer_id"] for _, v in rows])
        for rec, v in rows:
            tp = Taxpayer(
                **common,
                source_record_id=rec.id,
                source_taxpayer_id=v["source_taxpayer_id"],
                taxpayer_type=v["taxpayer_type"],
                status=v["status"],
                name_token=crypto.name_token(v["taxpayer_name"]),
                display_name=v["taxpayer_name"],
                jurisdiction_code=v["jurisdiction"],
                lga_code=v.get("lga_code"),
                sector=v.get("sector"),
                effective_from=v.get("effective_from"),
                effective_to=v.get("effective_to"),
            )
            db.add(tp)
            db.flush()
            tin = v["tin"]
            db.add(
                TaxpayerIdentifier(
                    tenant_id=actor.tenant_id,
                    taxpayer_id=tp.id,
                    identifier_type="TIN",
                    encrypted_value=crypto.encrypt(tin.encode(), str(tp.id).encode()),
                    token=crypto.identifier_token(tin),
                    masked=crypto.mask(tin),
                    verification_status="format_valid",
                    source_record_id=rec.id,
                )
            )
    elif feed == "ngsirs_employer":
        supersede("source_employer_id", [v["source_employer_id"] for _, v in rows])
        taxpayers = list(db.execute(select(Taxpayer).where(Taxpayer.is_current)).scalars())
        by_ref = {t.source_taxpayer_id: t for t in taxpayers}
        by_lga: dict[str | None, list[Taxpayer]] = defaultdict(list)
        for t in taxpayers:
            by_lga[t.lga_code].append(t)
        prior = identity.latest_matches(db)
        for rec, v in rows:
            new_emp = Employer(
                **common,
                source_record_id=rec.id,
                source_employer_id=v["source_employer_id"],
                linked_taxpayer_ref=v.get("linked_taxpayer_id"),
                display_name=v["employer_name"],
                activity_from=v.get("activity_from"),
                activity_to=v.get("activity_to"),
                office_code=v.get("office_id"),
                lga_code=v.get("lga_code"),
                sector=v.get("sector"),
                segment=v.get("segment"),
                status=v["status"],
            )
            db.add(new_emp)
            db.flush()
            identity.resolve_employer(db, tenant, new_emp, by_ref, by_lga, rec.id, prior)
    elif feed == "ngsirs_obligation":
        keys = [
            f"{v['taxpayer_id']}|{v['tax_type']}|{v['obligation_type']}|{v['effective_from']}"
            for _, v in rows
        ]
        supersede("natural_key", keys)
        for (rec, v), key in zip(rows, keys, strict=True):
            emp = employers.get(v["taxpayer_id"])
            db.add(
                TaxObligation(
                    **common,
                    source_record_id=rec.id,
                    natural_key=key,
                    employer_id=emp.id if emp else None,
                    taxpayer_ref=v["taxpayer_id"],
                    tax_type=v["tax_type"],
                    obligation_type=v["obligation_type"],
                    legal_code=v.get("legal_code") or "PAYE_EMPLOYER_MONTHLY_RETURN",
                    statutory_version=v.get("statutory_version"),
                    effective_from=v["effective_from"],
                    effective_to=v.get("effective_to"),
                    exemption_status=v.get("exemption_status") or "none",
                    status=v["status"],
                )
            )
    elif feed == "ngsirs_extension":
        keys = [f"{v['employer_id']}|{v['obligation_type']}|{v['period']}" for _, v in rows]
        supersede("natural_key", keys)
        from .legal import end_of_day_wat

        for (rec, v), key in zip(rows, keys, strict=True):
            emp = employers.get(v["employer_id"])
            db.add(
                Extension(
                    **common,
                    source_record_id=rec.id,
                    natural_key=key,
                    employer_id=emp.id if emp else None,
                    employer_ref=v["employer_id"],
                    obligation_type=v["obligation_type"],
                    period_code=v["period"],
                    new_due_at=end_of_day_wat(v["new_due_date"]),
                    status=v["status"],
                    approved_by=v.get("approved_by"),
                )
            )
    elif feed == "ngsirs_paye_return":
        keys = [f"{source.source_name}|{v['filing_reference']}" for _, v in rows]
        supersede("natural_key", keys)
        for (rec, v), key in zip(rows, keys, strict=True):
            emp = employers.get(v["employer_id"])
            db.add(
                ReturnFiling(
                    **common,
                    source_record_id=rec.id,
                    natural_key=key,
                    source_name=source.source_name,
                    employer_id=emp.id if emp else None,
                    employer_ref=v["employer_id"],
                    tax_type="PAYE",
                    period_code=v["period"],
                    filing_reference=v["filing_reference"],
                    submitted_at=v.get("submitted_at"),
                    accepted_at=v.get("accepted_at"),
                    status=v["status"],
                    amount_declared=v.get("amount_declared"),
                    employee_count=v.get("employee_count"),
                )
            )
    elif feed == "ngsirs_payment":
        keys = [f"{source.source_name}|{v['payment_reference']}" for _, v in rows]
        old_ids = list(
            db.execute(select(Payment.id).where(Payment.natural_key.in_(keys), Payment.is_current)).scalars()
        )
        if old_ids:
            db.execute(
                update(PaymentAllocation)
                .where(PaymentAllocation.payment_id.in_(old_ids))
                .values(is_current=False)
            )
        supersede("natural_key", keys)
        for (rec, v), key in zip(rows, keys, strict=True):
            emp = employers.get(v.get("employer_id") or "")
            alloc = v.get("allocation_status") or ("allocated" if emp and v.get("period") else "unallocated")
            if emp is None:
                alloc = "unallocated"
            pay = Payment(
                **common,
                source_record_id=rec.id,
                natural_key=key,
                payment_reference=v["payment_reference"],
                employer_id=emp.id if emp else None,
                employer_ref=v.get("employer_id"),
                tax_type=v["tax_type"],
                period_code=v.get("period"),
                paid_at=v["paid_at"],
                amount=v["amount"],
                reversal_status=v["reversal_status"],
                settlement_status=v.get("settlement_status") or "settled",
                allocation_status=alloc,
                bank_delay_dispute=bool(v.get("bank_delay_dispute")),
                credit_adjustment=v.get("credit_adjustment") or Decimal("0"),
            )
            db.add(pay)
            db.flush()
            if alloc == "allocated" and emp is not None and v.get("period"):
                db.add(
                    PaymentAllocation(
                        tenant_id=actor.tenant_id,
                        payment_id=pay.id,
                        employer_id=emp.id,
                        period_code=v["period"],
                        allocated_amount=v["amount"],
                    )
                )
    elif feed == "ngsirs_assessment":
        keys = [v["assessment_id"] for _, v in rows]
        supersede("natural_key", keys)
        for (rec, v), key in zip(rows, keys, strict=True):
            emp = employers.get(v["employer_id"])
            db.add(
                Assessment(
                    **common,
                    source_record_id=rec.id,
                    natural_key=key,
                    assessment_ref=v["assessment_id"],
                    employer_id=emp.id if emp else None,
                    employer_ref=v["employer_id"],
                    period_code=v["period"],
                    assessment_type=v["assessment_type"],
                    amount=v["amount"],
                    served_on=v.get("served_on"),
                    due_date=v.get("due_date"),
                    appeal_status=v["appeal_status"],
                    outstanding_amount=v["outstanding_amount"],
                    status=v["status"],
                )
            )

    if batch.coverage_from and batch.coverage_to:
        for p in period_range(batch.coverage_from, batch.coverage_to):
            db.add(
                SourceCoverage(
                    tenant_id=actor.tenant_id,
                    feed_type=feed,
                    period_code=p,
                    scope_lga=batch.coverage_lga,
                    batch_id=batch.id,
                    complete=True,
                    reconciled=True,
                )
            )
    batch.qa_status = "committed"
    batch.committed_by = actor.actor_id
    batch.committed_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        actor,
        "import.batch_committed",
        f"batch:{batch.id}",
        {"feed_type": feed, "canonical_rows": len(rows)},
    )
    return batch


def rollback_batch(db: Session, actor: Principal, batch_id: uuid.UUID, reason: str) -> IngestBatch:
    batch = db.get(IngestBatch, batch_id)
    if batch is None:
        raise not_found("Import batch")
    if batch.qa_status not in ("committed", "validated"):
        raise conflict(f"Batch is {batch.qa_status}; nothing to roll back")
    if batch.qa_status == "committed":
        model = CANONICAL_MODELS[batch.feed_type]
        if batch.feed_type == "ngsirs_payment":
            ids = list(db.execute(select(Payment.id).where(Payment.batch_id == batch.id)).scalars())
            if ids:
                db.execute(
                    update(PaymentAllocation)
                    .where(PaymentAllocation.payment_id.in_(ids))
                    .values(is_current=False)
                )
            restored = list(
                db.execute(select(Payment.id).where(Payment.superseded_by_batch_id == batch.id)).scalars()
            )
            if restored:
                db.execute(
                    update(PaymentAllocation)
                    .where(PaymentAllocation.payment_id.in_(restored))
                    .values(is_current=True)
                )
        db.execute(update(model).where(model.batch_id == batch.id).values(is_current=False))
        db.execute(
            update(model)
            .where(model.superseded_by_batch_id == batch.id)
            .values(is_current=True, superseded_by_batch_id=None)
        )
        db.execute(update(SourceCoverage).where(SourceCoverage.batch_id == batch.id).values(is_current=False))
        rec_ids = select(SourceRecord.id).where(SourceRecord.batch_id == batch.id)
        db.execute(
            update(IdentityMatch)
            .where(
                IdentityMatch.source_record_id.in_(rec_ids),
                IdentityMatch.status.in_(["auto_linked", "pending_review"]),
            )
            .values(status="retracted", reason=f"batch rolled back: {reason}")
        )
    batch.qa_status = "rolled_back"
    batch.rolled_back_by = actor.actor_id
    batch.rolled_back_at = datetime.now(UTC)
    db.flush()
    audit.record(db, actor, "import.batch_rolled_back", f"batch:{batch.id}", {"reason": reason})
    return batch


def resolve_quarantine(
    db: Session, actor: Principal, record_id: uuid.UUID, resolution: str, note: str
) -> SourceRecord:
    rec = db.get(SourceRecord, record_id)
    if rec is None:
        raise not_found("Quarantined record")
    if rec.status != "quarantined":
        raise conflict("Record is not quarantined")
    if resolution not in ("excluded", "corrected_at_source", "escalated"):
        raise unprocessable("resolution must be excluded, corrected_at_source or escalated")
    rec.resolution = resolution
    rec.resolved_by = actor.actor_id
    rec.resolved_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        actor,
        "quality.quarantine_resolved",
        f"source_record:{rec.id}",
        {"resolution": resolution, "note": note, "reasons": rec.reason_codes},
    )
    return rec


def batch_payload(b: IngestBatch, source_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(b.id),
        "seq": b.seq,
        "source": source_name or b.manifest.get("source"),
        "feed_type": b.feed_type,
        "file_name": b.file_name,
        "content_hash": b.content_hash,
        "schema_version": b.schema_version,
        "extracted_at": b.extracted_at.isoformat(),
        "ingested_at": b.ingested_at.isoformat(),
        "coverage": {"from": b.coverage_from, "to": b.coverage_to, "lga": b.coverage_lga},
        "qa_status": b.qa_status,
        "rows": b.row_count,
        "accepted": b.accepted_count,
        "quarantined": b.quarantined_count,
        "rejected": b.rejected_count,
        "quality": b.quality_report,
        "manifest_signature": b.manifest_signature,
        "created_by": b.created_by,
        "committed_by": b.committed_by,
        "committed_at": b.committed_at.isoformat() if b.committed_at else None,
        "rolled_back_by": b.rolled_back_by,
    }


__all__ = [
    "COMMIT_ORDER",
    "batch_payload",
    "commit_batch",
    "create_batch",
    "resolve_quarantine",
    "rollback_batch",
]
