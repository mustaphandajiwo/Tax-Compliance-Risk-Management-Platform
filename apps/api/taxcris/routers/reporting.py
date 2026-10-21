"""Metrics, role-based exports (FR-08, FR-10) and the audit trail (FR-09)."""

import csv
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from .. import audit
from ..config import today
from ..deps import DB, Principal, require
from ..domain import metrics as metric_catalogue
from ..models import Alert, AuditEvent, IdentityLink, RiskAssessment, Taxpayer
from ..permissions import P
from ..schemas import AuditEventOut, ChainVerification, Page
from ._common import Limit, Offset, log, paginate

router = APIRouter(prefix="/v1", tags=["metrics, exports & audit"])

PeriodQ = Query(None, pattern=r"^\d{4}(-(0[1-9]|1[0-2]))?$", description="YYYY or YYYY-MM; defaults to current year")


@router.get("/metrics", summary="Approved metric definitions with numerator, denominator and freshness")
def get_metrics(
    db: DB, principal: Annotated[Principal, Depends(require(P.METRICS_READ))],
    period: str | None = PeriodQ, tax_type: str | None = None, lga: str | None = None, sector: str | None = None,
    as_of: date | None = None,
) -> dict:
    return metric_catalogue.compute(db, principal.tenant_id, period=period or str(today().year), tax_type=tax_type,
                                    lga=lga, sector=sector, as_of=as_of or today())


@router.get("/metrics/definitions")
def metric_definitions(_: Annotated[Principal, Depends(require(P.METRICS_READ))]) -> dict:
    return {"metric_version": metric_catalogue.METRIC_VERSION, "definitions": metric_catalogue.DEFINITIONS}


def _csv(rows: list[list], header: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/exports/management-brief.csv", summary="Aggregate management brief (no taxpayer-level data)")
def export_brief(
    db: DB, principal: Annotated[Principal, Depends(require(P.EXPORTS_AGGREGATE))],
    period: str | None = PeriodQ, tax_type: str | None = None, lga: str | None = None, sector: str | None = None,
) -> StreamingResponse:
    m = metric_catalogue.compute(db, principal.tenant_id, period=period or str(today().year), tax_type=tax_type,
                                 lga=lga, sector=sector, as_of=today())
    rows = [[x["key"], x["label"], x["value"], x["numerator"], x["denominator"], x["coverage"], x["definition"]]
            for x in m["metrics"]]
    rows += [[f"timely_filing_rate[{b['lga']}]", f"Timely filing — {b['lga']}", b["value"], b["numerator"], b["denominator"], "", ""]
             for b in m["breakdowns"]["timely_filing_by_lga"]]
    log(db, principal, "export.management_brief", "export", None, filters=m["filters"], rows=len(rows))
    db.commit()
    return _csv(rows, ["metric", "label", "value", "numerator", "denominator", "coverage", "definition"], "management-brief.csv")


@router.get("/exports/alerts.csv", summary="Record-level alert export, masked by role")
def export_alerts(
    db: DB, principal: Annotated[Principal, Depends(require(P.EXPORTS_RECORDS))],
    status: str | None = None, period: str | None = PeriodQ, tax_type: str | None = None,
) -> StreamingResponse:
    q = (select(Alert, Taxpayer, RiskAssessment).join(Taxpayer, Taxpayer.id == Alert.taxpayer_id)
         .join(RiskAssessment, RiskAssessment.id == Alert.assessment_id)
         .where(Alert.tenant_id == principal.tenant_id).order_by(Alert.priority.desc()))
    for col, val in ((Alert.status, status), (Alert.period, period), (Alert.tax_type, tax_type)):
        if val:
            q = q.where(col == val)
    rows_db = db.execute(q.limit(10_000)).all()
    tins = {}
    ids = [t.id for _, t, _ in rows_db]
    if ids:
        for link in db.execute(select(IdentityLink).where(IdentityLink.taxpayer_id.in_(ids), IdentityLink.identifier_type == "TIN")).scalars():
            tins.setdefault(link.taxpayer_id, link.masked_value)
    rows = [[str(a.id), str(t.id), t.name, tins.get(t.id, ""), t.lga, t.sector, a.tax_type, a.period, a.status,
             a.priority, ra.confidence, str(ra.exposure_estimate), " ".join(ra.reason_codes)] for a, t, ra in rows_db]
    log(db, principal, "export.alerts", "export", None, rows=len(rows), masked=True,
        filters={"status": status, "period": period, "tax_type": tax_type})
    db.commit()
    return _csv(rows, ["alert_id", "taxpayer_id", "name", "tin_masked", "lga", "sector", "tax_type", "period", "status",
                       "priority", "confidence", "exposure_estimate", "reason_codes"], "alerts.csv")


@router.get("/audit-events", response_model=Page[AuditEventOut])
def audit_events(
    db: DB, principal: Annotated[Principal, Depends(require(P.AUDIT_LOG_READ))],
    action: str | None = None, actor_id: str | None = None, resource_type: str | None = None,
    resource_id: str | None = None, outcome: str | None = None, limit: int = Limit, offset: int = Offset,
) -> Page[AuditEventOut]:
    q = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id).order_by(AuditEvent.seq.desc())
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    for col, val in ((AuditEvent.resource_type, resource_type), (AuditEvent.resource_id, resource_id),
                     (AuditEvent.outcome, outcome)):
        if val:
            q = q.where(col == val)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    rows, total = paginate(db, q, limit, offset)
    return Page(items=[AuditEventOut.model_validate(r[0]) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/audit-events/verify", response_model=ChainVerification, summary="Recompute the tamper-evident hash chain")
def verify(db: DB, principal: Annotated[Principal, Depends(require(P.AUDIT_LOG_READ))]) -> dict:
    return audit.verify_chain(db, principal.tenant_id)
