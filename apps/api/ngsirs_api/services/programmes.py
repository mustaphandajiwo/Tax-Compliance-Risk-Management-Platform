"""Compliance programmes with intervention and comparison cohorts (PRD 7.3, FR-016/022).

Cohort assignment is deterministic (hash of programme id + employer) so it is
reproducible and auditable. Evaluation compares on-time filing before and after
for both groups and reports a simple difference-in-differences, always with
denominators and coverage.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import conflict, forbidden, not_found, unprocessable
from ..models import Employer, Programme, ProgrammeMember
from ..security.auth import Principal
from . import analytics, legal


def _group(programme_id: uuid.UUID, ref: str, share: float) -> str:
    h = int(hashlib.sha256(f"{programme_id}|{ref}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "comparison" if h < share else "intervention"


def create(db: Session, actor: Principal, data: dict[str, Any]) -> Programme:
    for a, b in (("baseline_from", "baseline_to"), ("evaluation_from", "evaluation_to")):
        if data[a] > data[b]:
            raise unprocessable(f"{a} is after {b}")
    if data["baseline_to"] >= data["evaluation_from"]:
        raise unprocessable("Baseline window must end before the evaluation window starts")
    if not 0 <= data.get("comparison_share", 0.3) <= 0.5:
        raise unprocessable("comparison_share must be between 0 and 0.5")
    p = Programme(
        tenant_id=actor.tenant_id,
        code=data["code"],
        name=data["name"],
        objective=data["objective"],
        population=data.get("population", {}),
        denominator_definition=data["denominator_definition"],
        baseline_from=data["baseline_from"],
        baseline_to=data["baseline_to"],
        evaluation_from=data["evaluation_from"],
        evaluation_to=data["evaluation_to"],
        intervention=data["intervention"],
        target=data["target"],
        resource_budget=data.get("resource_budget"),
        comparison_share=data.get("comparison_share", 0.3),
        status="draft",
        created_by=actor.actor_id,
    )
    db.add(p)
    db.flush()
    employers = db.execute(select(Employer).where(Employer.is_current)).scalars()
    pop = p.population or {}
    n = 0
    for e in employers:
        if pop.get("lga_codes") and e.lga_code not in pop["lga_codes"]:
            continue
        if pop.get("sectors") and e.sector not in pop["sectors"]:
            continue
        if pop.get("segments") and e.segment not in pop["segments"]:
            continue
        db.add(
            ProgrammeMember(
                tenant_id=actor.tenant_id,
                programme_id=p.id,
                employer_id=e.id,
                group_name=_group(p.id, e.source_employer_id, p.comparison_share),
            )
        )
        n += 1
    db.flush()
    audit.record(db, actor, "programme.created", f"programme:{p.code}", {"members": n, "population": pop})
    return p


def approve(db: Session, actor: Principal, p: Programme) -> Programme:
    if p.status != "draft":
        raise conflict(f"Programme is {p.status}")
    if p.created_by == actor.actor_id:
        raise forbidden("Segregation of duties: the creator cannot approve the programme")
    p.status = "approved"
    p.approved_by = actor.actor_id
    db.flush()
    audit.record(db, actor, "programme.approved", f"programme:{p.code}", {})
    return p


def evaluate(db: Session, actor: Principal, p: Programme) -> dict[str, Any]:
    run = analytics.latest_run(db)
    if run is None:
        raise conflict("No evaluation run available")
    records = analytics._employer_records(db, run)
    members = list(db.execute(select(ProgrammeMember).where(ProgrammeMember.programme_id == p.id)).scalars())
    refs = {e.id: e.source_employer_id for e in db.execute(select(Employer)).scalars()}
    groups: dict[str, set[str]] = {"intervention": set(), "comparison": set()}
    for m in members:
        if m.employer_id in refs:
            groups[m.group_name].add(refs[m.employer_id])
    windows = {
        "baseline": legal.period_range(p.baseline_from, p.baseline_to),
        "evaluation": legal.period_range(p.evaluation_from, p.evaluation_to),
    }
    result: dict[str, Any] = {
        "programme": p.code,
        "run_id": str(run.id),
        "as_of": run.as_of.isoformat(),
        "groups": {},
        "method": "Difference in on-time PAYE filing rate (evaluation minus "
        "baseline), intervention vs comparison. Denominator: obligated employers with "
        "complete filing coverage and a passed due date in each window.",
    }
    for g, refs_in in groups.items():
        result["groups"][g] = {"members": len(refs_in)}
        for w, periods in windows.items():
            num = den = obl = 0
            for period in periods:
                r = analytics.filing_rates(records, period, group=refs_in)
                num += r["numerator"]
                den += r["denominator"]
                obl += r["obligated"]
            result["groups"][g][w] = analytics.metric(
                f"{g}_{w}",
                f"{g} on-time filing ({w})",
                num,
                den,
                f"{periods[0]}..{periods[-1]}",
                round(den / obl, 4) if obl else None,
            )
    try:
        di = result["groups"]["intervention"]
        dc = result["groups"]["comparison"]
        change_i = di["evaluation"]["value"] - di["baseline"]["value"]
        change_c = dc["evaluation"]["value"] - dc["baseline"]["value"]
        result["difference_in_differences"] = round(change_i - change_c, 4)
    except TypeError:
        result["difference_in_differences"] = None
        result["caveat"] = "One or more rates withheld for low coverage or empty denominators"
    result["evaluated_at"] = datetime.now(UTC).isoformat()
    p.evaluation = result
    if p.status == "approved":
        p.status = "evaluated"
    db.flush()
    audit.record(
        db,
        actor,
        "programme.evaluated",
        f"programme:{p.code}",
        {"did": result.get("difference_in_differences")},
    )
    return result


def get(db: Session, programme_id: uuid.UUID) -> Programme:
    p = db.get(Programme, programme_id)
    if p is None:
        raise not_found("Programme")
    return p
