"""The compliance risk management cycle, measured from live data.

Six stages, each answered from the platform's own records rather than declared:

1. Identify risks          - sources, coverage, active rules, what the last evaluation raised
2. Assess and prioritise   - open findings by priority band; holds that block scoring
3. Analyse behaviour       - every taxpayer placed in one behaviour segment, with the matching strategy
4. Decide treatment        - findings awaiting a decision and cases awaiting approval; treatment mix
5. Implement and engage    - live cases, overdue work, recorded actions
6. Monitor and evaluate    - outcomes, rule precision, repeat findings after treatment, programme results

The cycle closes the loop: stage 6 results (rule precision, repeat findings) feed rule tuning and the
next stage-1 evaluation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from risk_engine.states import OPEN_FINDING_STATES, TERMINAL_FINDING_STATES
from risk_engine.treatment import TREATMENTS

from ..models import (
    CaseAction,
    CaseRecord,
    DataSource,
    Employer,
    EvaluationRun,
    InputSnapshot,
    Programme,
    RevenueAccount,
    RiskFinding,
    RuleDefinitionRow,
)
from ..security.auth import Principal
from ..serializers import cycle_stage, head_names
from .evaluation import load_snapshot

STAGES = [
    ("identify", "Identify risks", "Bring in data from every source, check coverage and run the rules."),
    (
        "assess",
        "Assess and prioritise",
        "Score likelihood and consequence; hold anything the data cannot support.",
    ),
    ("analyse", "Analyse behaviour", "Understand why taxpayers do not comply and group them by behaviour."),
    ("treat", "Decide treatment", "Match each risk to the lightest treatment that will work; approve it."),
    ("implement", "Implement and engage", "Carry out approved treatments and record every contact."),
    (
        "evaluate",
        "Monitor and evaluate",
        "Measure outcomes, tune rules and feed results into the next cycle.",
    ),
]
LINKS = {
    "identify": "/imports",
    "assess": "/risks",
    "analyse": "/taxpayers",
    "treat": "/risks?stage=treat",
    "implement": "/cases",
    "evaluate": "/programmes",
}

MISSING = {"FIL-001", "PAY-001", "FIL-101", "FIL-102", "PAY-101", "REG-101"}
LATE = {"FIL-002", "PAY-002", "FIL-103", "PAY-103"}
SHORT = {"PAY-004", "PAY-102"}
DEBT = {"PAY-006"}
HIDDEN = {"REG-102"}

SEGMENTS = [
    (
        "compliant",
        "Compliant",
        "Make it easy: pre-filled returns, simple payment, recognition and faster service",
    ),
    ("occasional", "Occasional slip", "Remind and inform: an approved reminder at the right moment"),
    ("struggling", "Trying but struggling", "Help: targeted assistance, education and payment arrangements"),
    ("outside", "Outside the net", "Bring in: registration drive and engagement on unreported activity"),
    (
        "persistent",
        "Persistent non-compliance",
        "Engage firmly: compliance engagement, desk review, lawful debt process",
    ),
    (
        "unclear",
        "Unclear: data first",
        "Fix the data before any contact: identity, coverage or legal verification",
    ),
]


def _latest_run(db: Session) -> EvaluationRun | None:
    return (
        db.execute(
            select(EvaluationRun)
            .where(EvaluationRun.mode == "operational", EvaluationRun.status == "completed")
            .order_by(EvaluationRun.finished_at.desc())
        )
        .scalars()
        .first()
    )


def _segment(findings: list[RiskFinding]) -> str:
    scored = [f for f in findings if not f.data_hold and f.signal_class != "data_quality"]
    if not scored:
        return "unclear"
    codes = Counter(f.rule_code for f in scored)
    missing = sum(n for c, n in codes.items() if c in MISSING)
    late = sum(n for c, n in codes.items() if c in LATE)
    if "FIL-003" in codes or missing >= 2 or (codes.keys() & DEBT and missing):
        return "persistent"
    if codes.keys() & HIDDEN:
        return "outside"
    if "PAY-003" in codes or late >= 2 or (late and codes.keys() & SHORT):
        return "struggling"
    return "occasional"


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _head_rates(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """On-time payment and filing rates per tax type from the latest evaluation snapshot."""
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"pay_den": 0, "pay_num": 0, "file_den": 0, "file_num": 0}
    )
    for r in records:
        f, cov = r.get("facts", {}), (r.get("quality") or {}).get("coverage") or {}
        if f.get("obligation_status") != "active":
            continue
        t = str(r.get("tax_type"))
        if r["kind"] == "employer_period":
            if f.get("return_due_passed") and cov.get("filing"):
                out[t]["file_den"] += 1
                out[t]["file_num"] += int(f["accepted_filing_count"] > 0 and not f.get("filing_late_days"))
            if f.get("payment_due_passed") and cov.get("payment"):
                out[t]["pay_den"] += 1
                out[t]["pay_num"] += int(f["settled_payment_count"] > 0 and not f.get("payment_late_days"))
        elif r["kind"] == "account_period":
            if f.get("return_required") and f.get("return_due_passed") and cov.get("filing"):
                if f["pattern"] != "transaction" or f["transaction_count"]:
                    out[t]["file_den"] += 1
                    out[t]["file_num"] += int(f["filed_count"] > 0 and not f.get("filing_late_days"))
            if f.get("liability_established") and f.get("payment_due_passed") and cov.get("payment"):
                out[t]["pay_den"] += 1
                out[t]["pay_num"] += int(
                    f["settled_payment_count"] > 0
                    and not f.get("payment_late_days")
                    and (f.get("residual_amount") or 0) <= 100
                )
    return out


def summary(db: Session, principal: Principal) -> dict[str, Any]:
    now = datetime.now(UTC)
    run = _latest_run(db)
    scope = principal.area_scope
    q = select(RiskFinding).where(RiskFinding.superseded_by_id.is_(None), RiskFinding.status != "withdrawn")
    if scope:
        q = q.where(RiskFinding.area_code.in_(scope))
    findings = list(db.execute(q).scalars())
    by_id = {f.id: f for f in findings}
    cases = [c for c in db.execute(select(CaseRecord)).scalars() if c.finding_id in by_id]
    live_case = {
        c.finding_id: c
        for c in sorted(cases, key=lambda c: c.created_at)
        if c.stage not in ("closed", "rejected")
    }
    open_f = [f for f in findings if f.status in OPEN_FINDING_STATES]
    stage_of = {
        f.id: cycle_stage(f.status, live_case[f.id].stage if f.id in live_case else None) for f in findings
    }
    names = head_names(db)

    # Who is each finding about? PAYE -> employer; other heads -> the account's taxpayer (else the account).
    accounts = {
        a.account_ref: a
        for a in db.execute(select(RevenueAccount).where(RevenueAccount.is_current)).scalars()
    }

    def who(f: RiskFinding) -> str:
        if f.subject_type == "account":
            a = accounts.get(f.subject_id)
            return (a.taxpayer_ref if a and a.taxpayer_ref else None) or f"account:{f.subject_id}"
        if f.subject_type == "taxpayer":
            return f.subject_id
        return f.employer_ref or f.subject_id

    # --- 1. Identify ---------------------------------------------------------------------------------------
    sources = list(db.execute(select(DataSource)).scalars())
    rules_active = db.execute(
        select(func.count())
        .select_from(RuleDefinitionRow)
        .where(RuleDefinitionRow.active_version_id.is_not(None))
    ).scalar_one()
    snap = db.get(InputSnapshot, run.snapshot_id) if run else None
    records: list[dict[str, Any]] = list(load_snapshot(snap)) if snap else []
    raised = sum(1 for f in findings if run and f.first_run_id == run.id)
    identify = {
        "headline": {"value": len(open_f), "label": "open risk signals"},
        "metrics": [
            {"label": "Revenue heads monitored", "value": len(names)},
            {"label": "Data sources enabled", "value": sum(1 for s in sources if s.enabled)},
            {"label": "Rules active", "value": rules_active},
            {"label": "Signals raised in the latest run", "value": raised},
            {"label": "Fact records evaluated", "value": len(records)},
        ],
        "note": "Only system-of-record sources count as evidence; coverage is checked per head and period.",
    }

    # --- 2. Assess and prioritise -------------------------------------------------------------------------
    bands = Counter((f.priority_band or ("held" if f.data_hold else "unscored")) for f in open_f)
    assess = {
        "headline": {
            "value": sum(1 for f in open_f if stage_of[f.id] == "assess"),
            "label": "awaiting assessment",
        },
        "metrics": [
            {"label": "Priority review", "value": bands.get("priority_review", 0)},
            {"label": "High", "value": bands.get("high", 0)},
            {"label": "Moderate", "value": bands.get("moderate", 0)},
            {"label": "Low", "value": bands.get("low", 0)},
            {"label": "Exposure unknown (ordered by likelihood)", "value": bands.get("unscored", 0)},
            {"label": "Held: data must be fixed first (no score)", "value": bands.get("held", 0)},
            {
                "label": "Legal hold or dispute (no outward action)",
                "value": sum(1 for f in open_f if f.legal_hold or f.disputed),
            },
        ],
        "note": "Priority = 4 x likelihood x consequence orders the queue only; confidence is shown separately.",
    }

    # --- 3. Analyse behaviour -----------------------------------------------------------------------------
    per_subject: dict[str, list[RiskFinding]] = defaultdict(list)
    for f in open_f:
        per_subject[who(f)].append(f)
    employers = db.execute(
        select(Employer.source_employer_id, Employer.area_code).where(Employer.is_current)
    ).all()
    population = {ref for ref, area in employers if not scope or area in scope}
    for a in accounts.values():
        if not scope or a.area_code in scope:
            population.add(a.taxpayer_ref or f"account:{a.account_ref}")
    population |= set(per_subject)
    seg_counts = Counter(_segment(v) for v in per_subject.values())
    seg_counts["compliant"] = len(population) - len(per_subject)
    segments = [
        {
            "key": k,
            "label": label,
            "count": seg_counts.get(k, 0),
            "share": _rate(seg_counts.get(k, 0), len(population)),
            "strategy": strategy,
        }
        for k, label, strategy in SEGMENTS
    ]
    analyse = {
        "headline": {"value": len(population), "label": "taxpayers and accounts segmented"},
        "metrics": [{"label": s["label"], "value": s["count"]} for s in segments],
        "note": "Each taxpayer is placed by the pattern of its open signals across every tax type.",
    }

    # --- 4. Decide treatment ------------------------------------------------------------------------------
    pending_cases = [c for c in cases if c.stage == "pending_approval"]
    mix = Counter(c.treatment for c in cases if c.stage not in ("rejected",))
    treat = {
        "headline": {
            "value": sum(1 for f in open_f if stage_of[f.id] == "treat"),
            "label": "awaiting a treatment decision",
        },
        "metrics": [
            {
                "label": "Confirmed, no case yet",
                "value": sum(
                    1 for f in open_f if f.status == "approved_for_treatment" and f.id not in live_case
                ),
            },
            {"label": "Cases awaiting manager approval", "value": len(pending_cases)},
            *[
                {"label": TREATMENTS[t].label if t in TREATMENTS else t, "value": n}
                for t, n in mix.most_common(4)
            ],
        ],
        "note": "The officer who opens a case cannot approve it; outward contact needs an approved template.",
    }

    # --- 5. Implement and engage --------------------------------------------------------------------------
    live = [c for c in cases if c.stage in ("approved", "in_progress", "awaiting_response")]
    case_ids = [c.id for c in cases]
    actions = (
        list(db.execute(select(CaseAction).where(CaseAction.case_id.in_(case_ids))).scalars())
        if case_ids
        else []
    )
    implement = {
        "headline": {"value": len(live), "label": "cases being worked"},
        "metrics": [
            {
                "label": "Awaiting taxpayer response",
                "value": sum(1 for c in live if c.stage == "awaiting_response"),
            },
            {
                "label": "Overdue against target date",
                "value": sum(1 for c in live if c.due_at and c.due_at < now),
            },
            {"label": "Actions recorded", "value": len(actions)},
            {"label": "Taxpayer contacts recorded", "value": sum(1 for a in actions if a.template_code)},
        ],
        "note": "Demo environments never send messages; contacts are recorded as not sent.",
    }

    # --- 6. Monitor and evaluate --------------------------------------------------------------------------
    closed = [f for f in findings if f.status in TERMINAL_FINDING_STATES]
    outcome = Counter(f.status for f in closed)
    per_rule: dict[str, Counter[str]] = defaultdict(Counter)
    for f in closed:
        per_rule[f.rule_code][f.status] += 1
    precision = sorted(
        (
            {
                "rule": rule,
                "confirmed": c.get("closed_confirmed", 0),
                "not_substantiated": c.get("closed_not_substantiated", 0),
                "precision": _rate(
                    c.get("closed_confirmed", 0),
                    c.get("closed_confirmed", 0) + c.get("closed_not_substantiated", 0),
                ),
            }
            for rule, c in per_rule.items()
        ),
        key=lambda r: str(r["rule"]),
    )
    closed_cases = [c for c in cases if c.stage == "closed" and c.closed_at]
    repeat = 0
    for c in closed_cases:
        cf = by_id.get(c.finding_id)
        if cf is None or c.closed_at is None:
            continue
        subject, closed_at = who(cf), c.closed_at
        if any(who(g) == subject and g.created_at > closed_at for g in findings if g.id != cf.id):
            repeat += 1
    programmes = list(db.execute(select(Programme)).scalars())
    decided = outcome.get("closed_confirmed", 0) + outcome.get("closed_not_substantiated", 0)
    evaluate = {
        "headline": {"value": len(closed), "label": "signals closed with an outcome"},
        "metrics": [
            {"label": "Confirmed", "value": outcome.get("closed_confirmed", 0)},
            {"label": "Not substantiated", "value": outcome.get("closed_not_substantiated", 0)},
            {"label": "Corrected (data or record fixed)", "value": outcome.get("corrected", 0)},
            {
                "label": "Rule precision (confirmed / decided)",
                "value": _rate(outcome.get("closed_confirmed", 0), decided),
                "unit": "rate",
            },
            {
                "label": "New signals after a closed case",
                "value": repeat,
                "note": f"of {len(closed_cases)} closed cases",
            },
            {"label": "Programmes with an evaluation design", "value": len(programmes)},
        ],
        "note": "Results feed back: low-precision rules are revised through the governed rule studio "
        "before the next run.",
    }

    stage_payload: dict[str, dict[str, Any]] = {
        "identify": identify,
        "assess": assess,
        "analyse": analyse,
        "treat": treat,
        "implement": implement,
        "evaluate": evaluate,
    }

    # --- By tax type --------------------------------------------------------------------------------------
    rates = _head_rates(records)
    head_rows = []
    acct_counts = Counter(a.tax_head for a in accounts.values() if a.status == "active")
    for code, name in names.items():
        fs = [f for f in open_f if f.tax_type == code]
        r = rates.get(code, {})
        st = Counter(stage_of[f.id] for f in fs)
        head_rows.append(
            {
                "tax_type": code,
                "name": name,
                "accounts": len(population & {ref for ref, _ in employers})
                if code == "PAYE"
                else acct_counts.get(code, 0),
                "open_findings": len(fs),
                "held": sum(1 for f in fs if f.data_hold),
                "assess": st.get("assess", 0),
                "treat": st.get("treat", 0),
                "implement": st.get("implement", 0),
                "on_time_filing": {
                    "value": _rate(r.get("file_num", 0), r.get("file_den", 0)),
                    "denominator": r.get("file_den", 0),
                },
                "on_time_payment": {
                    "value": _rate(r.get("pay_num", 0), r.get("pay_den", 0)),
                    "denominator": r.get("pay_den", 0),
                },
            }
        )

    return {
        "generated_at": now.isoformat(),
        "as_of": run.as_of.isoformat() if run else None,
        "window": [run.period_from, run.period_to] if run else None,
        "stages": [
            {"key": k, "label": label, "purpose": purpose, "link": LINKS[k], **stage_payload[k]}
            for k, label, purpose in STAGES
        ],
        "segments": segments,
        "by_tax_type": head_rows,
        "precision": precision,
        "synthetic_data": True,
        "method_note": (
            "Stages are computed from findings, cases and the latest evaluation snapshot. On-time rates use "
            "periods whose due date has passed and whose source coverage is complete; a liability counts only "
            "once established (return filed, demand served, levy or renewal due). SYNTHETIC DATA."
        ),
    }
