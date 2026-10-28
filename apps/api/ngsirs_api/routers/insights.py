"""Dashboard, analytics, management reports, programmes, audit and reference data."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from risk_engine.treatment import TREATMENTS

from .. import audit
from ..errors import not_found
from ..models import (
    AppUser,
    AuditEvent,
    CaseRecord,
    EvaluationRun,
    IngestBatch,
    Lga,
    Programme,
    ProgrammeMember,
    RetentionPolicy,
    RiskFinding,
    SourceRecord,
    TaxOffice,
)
from ..schemas import ProgrammeCreate
from ..security.auth import Principal, declared_purpose, get_db, require
from ..security.rbac import PURPOSES, ROLES
from ..services import analytics, programmes

router = APIRouter(prefix="/api/v1", tags=["insights"])

METHOD_NOTE = (
    "Method: rates use the latest operational evaluation snapshot. Denominator = employers with an "
    "active, legally approved PAYE obligation whose due date has passed and whose source coverage is "
    "complete. Rates are withheld below 80% completeness. SYNTHETIC DATA."
)


@router.get("/dashboard/summary")
def dashboard(
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    lga: str | None = None,
    tax_type: str = "PAYE",
    _: Principal = Depends(require("dashboard:read")),
    db: Session = Depends(get_db),
) -> dict:
    out = analytics.summary(db, period, lga)
    out["method_note"] = METHOD_NOTE
    return out


@router.get("/analytics/compliance")
def compliance(
    period: str | None = None,
    _: Principal = Depends(require("dashboard:read")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "rows": analytics.lga_breakdown_rows(db, period),
        "method_note": METHOD_NOTE,
        "freshness": analytics.source_freshness(db),
    }


REPORTS = {
    "compliance_by_lga": "PAYE on-time filing and remittance by LGA with denominators and completeness",
    "findings_register": "Open findings with rule, period, indicators, holds and status",
    "case_outcomes": "Cases with treatment, stage, approvals and outcomes",
    "data_quality": "Quarantined records and reasons",
}


@router.get("/reports")
def list_reports(_: Principal = Depends(require("reports:read"))) -> list[dict]:
    return [{"name": k, "description": v, "formats": ["csv", "json"]} for k, v in REPORTS.items()]


@router.get("/reports/{name}", response_model=None)
def report(
    name: str,
    period: str | None = None,
    format: str = Query("json", pattern="^(json|csv)$"),
    purpose: str | None = Header(default=None, alias="X-Purpose"),
    principal: Principal = Depends(require("reports:read")),
    db: Session = Depends(get_db),
) -> Response | dict:
    if name not in REPORTS:
        raise not_found("Report")
    if name == "compliance_by_lga":
        rows = analytics.lga_breakdown_rows(db, period)
    elif name == "findings_register":
        if "executive_viewer" in principal.roles and len(principal.roles) == 1:
            rows = [
                {"rule_code": r, "signal_class": c, "status": s, "count": n}
                for r, c, s, n in db.execute(
                    select(
                        RiskFinding.rule_code, RiskFinding.signal_class, RiskFinding.status, func.count()
                    ).group_by(RiskFinding.rule_code, RiskFinding.signal_class, RiskFinding.status)
                ).all()
            ]
        else:
            rows = [
                {
                    "finding_ref": f.finding_ref,
                    "rule_code": f.rule_code,
                    "rule_version": f.rule_version,
                    "signal_class": f.signal_class,
                    "subject": f.subject_id,
                    "lga": f.lga_code,
                    "period": f.period_code,
                    "likelihood": f.likelihood,
                    "consequence": f.consequence,
                    "confidence": f.confidence,
                    "priority": f.priority,
                    "data_hold": f.data_hold,
                    "legal_hold": f.legal_hold,
                    "status": f.status,
                    "legal_version": f.legal_version_label,
                }
                for f in db.execute(
                    select(RiskFinding)
                    .where(RiskFinding.superseded_by_id.is_(None))
                    .order_by(RiskFinding.rule_code, RiskFinding.subject_id)
                ).scalars()
            ]
    elif name == "case_outcomes":
        rows = [
            {
                "case_ref": c.case_ref,
                "treatment": c.treatment,
                "stage": c.stage,
                "outcome": c.outcome,
                "created_by": c.created_by,
                "approved_by": c.approved_by,
                "outward_permitted": c.outward_permitted,
                "created_at": c.created_at.isoformat(),
                "closed_at": c.closed_at.isoformat() if c.closed_at else "",
            }
            for c in db.execute(select(CaseRecord).order_by(CaseRecord.created_at)).scalars()
        ]
    else:
        rows = [
            {
                "feed_type": r.feed_type,
                "row": r.row_number,
                "natural_id": r.natural_id,
                "reasons": ";".join(r.reason_codes),
                "resolution": r.resolution or "",
            }
            for r in db.execute(select(SourceRecord).where(SourceRecord.status == "quarantined")).scalars()
        ]
    meta = {
        "report": name,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": principal.actor_id,
        "period": period,
        "rows": len(rows),
        "method_note": METHOD_NOTE,
    }
    if format == "csv":
        if not principal.can("reports:export"):
            from ..errors import forbidden

            raise forbidden("Role lacks permission 'reports:export'")
        p = declared_purpose(principal, purpose)
        buf = io.StringIO()
        buf.write(
            f"# {REPORTS[name]}\n# {METHOD_NOTE}\n# generated {meta['generated_at']} by {principal.actor_id}\n"
        )
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        audit.record(db, principal, "report.exported", f"report:{name}", {"rows": len(rows)}, purpose=p)
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    return {"meta": meta, "rows": rows}


# --- programmes -------------------------------------------------------------------------


def _programme_payload(db: Session, p: Programme) -> dict:
    counts = dict(
        db.execute(
            select(ProgrammeMember.group_name, func.count())
            .where(ProgrammeMember.programme_id == p.id)
            .group_by(ProgrammeMember.group_name)
        ).all()
    )
    return {
        "id": str(p.id),
        "code": p.code,
        "name": p.name,
        "objective": p.objective,
        "population": p.population,
        "denominator_definition": p.denominator_definition,
        "baseline": [p.baseline_from, p.baseline_to],
        "evaluation_window": [p.evaluation_from, p.evaluation_to],
        "intervention": p.intervention,
        "target": p.target,
        "resource_budget": p.resource_budget,
        "comparison_share": p.comparison_share,
        "status": p.status,
        "created_by": p.created_by,
        "approved_by": p.approved_by,
        "members": counts,
        "evaluation": p.evaluation,
    }


@router.get("/programmes")
def list_programmes(
    _: Principal = Depends(require("programmes:read")), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        _programme_payload(db, p)
        for p in db.execute(select(Programme).order_by(Programme.created_at)).scalars()
    ]


@router.post("/programmes", status_code=201)
def create_programme(
    body: ProgrammeCreate,
    principal: Principal = Depends(require("programmes:manage")),
    db: Session = Depends(get_db),
) -> dict:
    return _programme_payload(db, programmes.create(db, principal, body.model_dump()))


@router.get("/programmes/{programme_id}")
def get_programme(
    programme_id: uuid.UUID, _: Principal = Depends(require("programmes:read")), db: Session = Depends(get_db)
) -> dict:
    return _programme_payload(db, programmes.get(db, programme_id))


@router.post("/programmes/{programme_id}/approve")
def approve_programme(
    programme_id: uuid.UUID,
    principal: Principal = Depends(require("programmes:approve")),
    db: Session = Depends(get_db),
) -> dict:
    return _programme_payload(db, programmes.approve(db, principal, programmes.get(db, programme_id)))


@router.post("/programmes/{programme_id}/evaluate")
def evaluate_programme(
    programme_id: uuid.UUID,
    principal: Principal = Depends(require("programmes:manage")),
    db: Session = Depends(get_db),
) -> dict:
    return programmes.evaluate(db, principal, programmes.get(db, programme_id))


# --- audit ---------------------------------------------------------------------------------


@router.get("/audit-events")
def audit_events(
    event_type: str | None = None,
    subject: str | None = None,
    actor: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    _: Principal = Depends(require("audit:read")),
    db: Session = Depends(get_db),
) -> dict:
    q = select(AuditEvent)
    if event_type:
        q = q.where(AuditEvent.event_type.like(f"{event_type}%"))
    if subject:
        q = q.where(AuditEvent.subject_ref == subject)
    if actor:
        q = q.where(AuditEvent.actor_id == actor)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(AuditEvent.seq.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars()
    return {
        "total": total,
        "items": [
            {
                "seq": e.seq,
                "actor": e.actor_id,
                "roles": e.actor_roles,
                "event_type": e.event_type,
                "subject": e.subject_ref,
                "purpose": e.purpose,
                "details": e.details,
                "before_hash": e.before_hash,
                "after_hash": e.after_hash,
                "trace_id": e.trace_id,
                "occurred_at": e.occurred_at.isoformat(),
                "event_hash": e.event_hash,
                "prev_hash": e.prev_hash,
            }
            for e in rows
        ],
    }


@router.get("/audit-events/verify")
def verify_audit(
    principal: Principal = Depends(require("audit:read")), db: Session = Depends(get_db)
) -> dict:
    return audit.verify_chain(db, principal.tenant_id)


# --- reference & operations ------------------------------------------------------------------


@router.get("/reference")
def reference(_: Principal = Depends(require("reference:read")), db: Session = Depends(get_db)) -> dict:
    return {
        "lgas": [
            {"code": lg.code, "name": lg.name, "verified": lg.verified, "pilot": lg.pilot}
            for lg in db.execute(select(Lga).order_by(Lga.name)).scalars()
        ],
        "offices": [
            {"code": o.code, "name": o.name, "lga": o.lga_code}
            for o in db.execute(select(TaxOffice).order_by(TaxOffice.code)).scalars()
        ],
        "roles": ROLES,
        "purposes": PURPOSES,
        "treatments": {
            k: {
                "label": t.label,
                "human_gate": t.human_gate,
                "outward": t.outward,
                "approver_roles": t.approver_roles,
            }
            for k, t in TREATMENTS.items()
        },
        "users": [
            {"username": u.username, "display_name": u.display_name, "roles": u.roles, "unit": u.unit}
            for u in db.execute(select(AppUser).where(AppUser.active).order_by(AppUser.username)).scalars()
        ],
    }


@router.get("/ops/metrics")
def ops_metrics(_: Principal = Depends(require("ops:read")), db: Session = Depends(get_db)) -> dict:
    last = analytics.latest_run(db)
    batches = list(db.execute(select(IngestBatch).order_by(IngestBatch.seq.desc()).limit(50)).scalars())
    return {
        "source_freshness": analytics.source_freshness(db),
        "recent_batches": [
            {
                "seq": b.seq,
                "feed_type": b.feed_type,
                "status": b.qa_status,
                "rows": b.row_count,
                "rejected": b.rejected_count,
                "quarantined": b.quarantined_count,
            }
            for b in batches
        ],
        "last_run": {
            "id": str(last.id),
            "counts": last.counts,
            "duration_seconds": (last.finished_at - last.started_at).total_seconds()
            if last.finished_at
            else None,
        }
        if last
        else None,
        "runs_total": db.execute(select(func.count()).select_from(EvaluationRun)).scalar_one(),
        "retention_policies": [
            {
                "data_class": r.data_class,
                "retain_days": r.retain_days,
                "action": r.action,
                "legal_basis": r.legal_basis,
            }
            for r in db.execute(select(RetentionPolicy)).scalars()
        ],
    }
