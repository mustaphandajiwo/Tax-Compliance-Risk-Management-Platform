"""Compliance signal engine and explainable risk scoring (FR-04, FR-05, PRD §6).

Pipeline per taxpayer and run scope (tax type + period):

1. ``build_inputs`` freezes everything the evaluation needs into a JSON snapshot (obligations,
   returns, payments, identity certainty, feed freshness). The snapshot and its hash are stored.
2. ``evaluate(inputs, config)`` is a *pure function* of the snapshot and the approved model
   configuration. Re-running it on stored inputs must reproduce the stored output hash exactly.

Scoring: each applicable dimension (registration, filing, reporting, payment) gets a 0–100 score;
non-applicable dimensions are excluded and the remaining weights renormalised. Data confidence is
computed independently. When confidence is below the model's minimum, adverse prioritisation is
suppressed and the case is referred for data verification instead.

A signal is an indicator for human review — never proof of evasion.
"""

import statistics
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..models import (
    Alert,
    IdentityLink,
    ImportBatch,
    LegalRule,
    MergeCandidate,
    Payment,
    RiskAssessment,
    RiskModel,
    RiskRun,
    RiskSignal,
    Taxpayer,
    TaxObligation,
    TaxReturn,
    Tenant,
)
from ..security import sha256_json
from . import obligations as obligation_engine

ENGINE_VERSION = "signals-1.0.0"
DIMENSIONS = ("registration", "filing", "reporting", "payment")
CRITICAL_COMPONENT, CRITICAL_CAP = 0.25, 0.5

DEFAULT_WEIGHTS = {"registration": 0.15, "filing": 0.25, "reporting": 0.35, "payment": 0.25}
DEFAULT_THRESHOLDS = {
    "alert_score": 25.0,
    "alert_signal_severity": 85.0,
    "min_confidence": 0.6,
    "payment_tolerance": 0.05,
    "income_deviation_pct": 0.4,
    "feed_staleness_days": 35,
}

SIGNAL_CATALOGUE: dict[str, dict[str, str]] = {
    "REG-001": {"dimension": "registration", "title": "Entity in authorised dataset not registered for tax"},
    "FIL-001": {"dimension": "filing", "title": "Required return not received by legal deadline"},
    "FIL-002": {"dimension": "filing", "title": "Return filed after legal deadline"},
    "PAY-001": {"dimension": "payment", "title": "Payment below declared liability"},
    "PAY-002": {"dimension": "payment", "title": "Liability paid after deadline"},
    "PAY-003": {"dimension": "payment", "title": "No payment against an obligation past its deadline"},
    "REP-001": {"dimension": "reporting", "title": "Material unexplained decline in reported income (hypothesis)"},
}


def _d(v: Any) -> Decimal:
    return Decimal(str(v))


def _money(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


# ---------------------------------------------------------------------------------------------
# 1. Input snapshot
# ---------------------------------------------------------------------------------------------


def feed_freshness(db: Session, tenant_id: uuid.UUID) -> dict[str, str | None]:
    rows = db.execute(
        select(ImportBatch.dataset, func.max(ImportBatch.extracted_at))
        .where(ImportBatch.tenant_id == tenant_id, ImportBatch.status == "completed")
        .group_by(ImportBatch.dataset)
    ).all()
    out: dict[str, str | None] = {k: None for k in ("taxpayers", "returns", "payments", "employments")}
    for ds, d in rows:
        out[ds] = d.isoformat() if d else None
    return out


def _history_periods(period: str, n: int) -> list[str]:
    if len(period) == 4:
        return [str(int(period) - i) for i in range(1, n + 1)]
    y, m = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return out


def build_inputs(
    db: Session,
    tenant: Tenant,
    tp: Taxpayer,
    tax_type: str,
    scope: str,
    as_of: date,
    feeds: dict[str, str | None],
    rule_codes: dict[uuid.UUID, str],
) -> dict[str, Any]:
    obs = [
        o
        for o in db.execute(
            select(TaxObligation).where(
                TaxObligation.tenant_id == tenant.id, TaxObligation.taxpayer_id == tp.id, TaxObligation.tax_type == tax_type
            )
        ).scalars()
        if obligation_engine._in_scope(o.period, scope) and o.status != "exempt"
    ]
    obs.sort(key=lambda o: o.period)
    returns = list(
        db.execute(
            select(TaxReturn).where(TaxReturn.tenant_id == tenant.id, TaxReturn.taxpayer_id == tp.id, TaxReturn.tax_type == tax_type)
        ).scalars()
    )
    payments = list(
        db.execute(
            select(Payment).where(Payment.tenant_id == tenant.id, Payment.taxpayer_id == tp.id, Payment.tax_type == tax_type)
        ).scalars()
    )
    scope_periods = {o.period for o in obs} | {
        r.period for r in returns if obligation_engine._in_scope(r.period, scope)
    }
    history_needed: set[str] = set()
    for p in scope_periods:
        history_needed.update(_history_periods(p, 12 if len(p) == 7 else 2))
    links = list(db.execute(select(IdentityLink).where(IdentityLink.taxpayer_id == tp.id)).scalars())
    pending_merge = db.execute(
        select(func.max(MergeCandidate.confidence)).where(
            MergeCandidate.tenant_id == tenant.id,
            MergeCandidate.status.in_(["candidate", "proposed"]),
            (MergeCandidate.survivor_id == tp.id) | (MergeCandidate.duplicate_id == tp.id),
        )
    ).scalar_one()
    return {
        "engine_version": ENGINE_VERSION,
        "as_of": as_of.isoformat(),
        "jurisdiction": tenant.state_code,
        "tax_type": tax_type,
        "scope": scope,
        "taxpayer": {
            "id": str(tp.id),
            "taxpayer_type": tp.taxpayer_type,
            "registration_status": tp.registration_status,
            "tax_residence": tp.tax_residence,
            "operating_status": tp.operating_status,
            "closed_on": tp.closed_on.isoformat() if tp.closed_on else None,
            "source": f"{tp.source_system}:{tp.source_record_id}",
        },
        "obligations": [
            {
                "id": str(o.id),
                "period": o.period,
                "due_date": o.due_date.isoformat(),
                "extension_until": o.extension_until.isoformat() if o.extension_until else None,
                "rule_code": rule_codes.get(o.legal_rule_id),
                "rule_version": o.rule_version,
            }
            for o in obs
        ],
        "returns": sorted(
            (
                {
                    "id": str(r.id),
                    "period": r.period,
                    "filing_date": r.filing_date.isoformat(),
                    "reported_income": _money(r.reported_income),
                    "reported_amount": _money(r.reported_amount),
                    "source": f"{r.source_system}:{r.source_record_id}",
                }
                for r in returns
                if r.period in scope_periods or r.period in history_needed
            ),
            key=lambda x: (x["period"], x["filing_date"], x["id"]),
        ),
        "payments": sorted(
            (
                {
                    "id": str(p.id),
                    "period": p.period,
                    "amount": _money(p.amount),
                    "payment_date": p.payment_date.isoformat(),
                    "allocation_status": p.allocation_status,
                    "source": f"{p.source_system}:{p.source_record_id}",
                }
                for p in payments
                if (p.period in scope_periods) or p.allocation_status == "unallocated"
            ),
            key=lambda x: (x["period"] or "", x["payment_date"], x["id"]),
        ),
        "identity": {
            "identifier_count": len(links),
            "min_match_confidence": min((link.match_confidence for link in links), default=0.0),
            "pending_merge_confidence": round(pending_merge, 3) if pending_merge is not None else None,
        },
        "feeds": feeds,
    }


# ---------------------------------------------------------------------------------------------
# 2. Pure evaluation
# ---------------------------------------------------------------------------------------------


def _signal(code: str, severity: float, confidence: float, explanation: str, *, exposure: Decimal = Decimal("0"),
            obligation_id: str | None = None, evidence: dict | None = None, safeguards: list | None = None,
            action: str, hypothesis: bool = False, reason: str | None = None) -> dict[str, Any]:
    return {
        "rule_id": code,
        "dimension": SIGNAL_CATALOGUE[code]["dimension"],
        "title": SIGNAL_CATALOGUE[code]["title"],
        "severity": round(min(100.0, max(0.0, severity)), 2),
        "confidence": round(confidence, 3),
        "exposure": _money(exposure),
        "reason_code": reason or code,
        "explanation": explanation,
        "is_hypothesis": hypothesis,
        "obligation_id": obligation_id,
        "evidence_ref": evidence or {},
        "safeguards": safeguards or [],
        "recommended_action": action,
    }


def evaluate(inputs: dict[str, Any], weights: dict[str, float], thresholds: dict[str, Any]) -> dict[str, Any]:
    th = {**DEFAULT_THRESHOLDS, **thresholds}
    as_of = date.fromisoformat(inputs["as_of"])
    tp = inputs["taxpayer"]
    feeds = inputs["feeds"]
    returns_by_period: dict[str, list[dict]] = {}
    for r in inputs["returns"]:
        returns_by_period.setdefault(r["period"], []).append(r)
    pays_by_period: dict[str, list[dict]] = {}
    for p in inputs["payments"]:
        if p["period"]:
            pays_by_period.setdefault(p["period"], []).append(p)
    unallocated = sum((_d(p["amount"]) for p in inputs["payments"] if p["allocation_status"] == "unallocated"), Decimal("0"))
    returns_feed = _date(feeds.get("returns"))
    payments_feed = _date(feeds.get("payments"))

    signals: list[dict] = []
    applicable = {"registration": True, "filing": False, "reporting": False, "payment": False}

    # --- Registration -------------------------------------------------------------------------
    if tp["registration_status"] == "unregistered":
        in_jurisdiction = tp["tax_residence"] == inputs["jurisdiction"]
        safeguards = [
            {"check": "jurisdiction", "result": "pass" if in_jurisdiction else "fail",
             "detail": f"Tax residence {tp['tax_residence']} vs tenant {inputs['jurisdiction']}"},
            {"check": "identity_verification", "result": "required",
             "detail": "Confirm identity and that a registration obligation applies before contact"},
        ]
        if in_jurisdiction:
            signals.append(_signal(
                "REG-001", 70, 0.75,
                "Entity appears in an authorised business dataset but has no tax registration in this state.",
                evidence={"taxpayer_source": tp["source"]}, safeguards=safeguards, action="educational_communication",
            ))

    # --- Filing and payment per obligation -----------------------------------------------------
    for ob in inputs["obligations"]:
        deadline = _date(ob["extension_until"]) or date.fromisoformat(ob["due_date"])
        if deadline >= as_of:
            continue  # not yet due; no adverse inference
        applicable["filing"] = True
        rets = returns_by_period.get(ob["period"], [])
        legal = {"rule_code": ob["rule_code"], "rule_version": ob["rule_version"], "deadline": deadline.isoformat()}
        if not rets:
            safeguards = []
            confidence = 0.95
            feed_ok = returns_feed is not None and returns_feed > deadline
            safeguards.append({"check": "returns_feed_freshness", "result": "pass" if feed_ok else "fail",
                               "detail": f"Returns feed extracted {feeds.get('returns') or 'never'}; deadline {deadline}"})
            if not feed_ok:
                confidence = 0.3
            safeguards.append({"check": "extension", "result": "applied" if ob["extension_until"] else "none"})
            if tp["operating_status"] == "dormant":
                confidence = min(confidence, 0.5)
                safeguards.append({"check": "operating_status", "result": "warn", "detail": "Taxpayer marked dormant"})
            else:
                safeguards.append({"check": "operating_status", "result": "pass", "detail": tp["operating_status"]})
            signals.append(_signal(
                "FIL-001", 75, confidence,
                f"No {inputs['tax_type']} return received for {ob['period']}; deadline {deadline} has passed.",
                obligation_id=ob["id"], evidence={"obligation": ob["id"], "legal_rule": legal}, safeguards=safeguards,
                action="filing_reminder",
            ))
        else:
            first = min(rets, key=lambda r: r["filing_date"])
            days_late = (date.fromisoformat(first["filing_date"]) - deadline).days
            if days_late > 0:
                signals.append(_signal(
                    "FIL-002", min(60, 20 + days_late), 0.95,
                    f"Return for {ob['period']} filed {days_late} day(s) after the {deadline} deadline.",
                    obligation_id=ob["id"], evidence={"obligation": ob["id"], "return": first["id"], "legal_rule": legal},
                    action="educational_communication",
                ))

        # Payment
        latest = max(rets, key=lambda r: (r["filing_date"], r["id"])) if rets else None
        liability = _d(latest["reported_amount"]) if latest else None
        pays = pays_by_period.get(ob["period"], [])
        allocated = [p for p in pays if p["allocation_status"] == "allocated" and date.fromisoformat(p["payment_date"]) <= as_of]
        disputed = sum((_d(p["amount"]) for p in pays if p["allocation_status"] == "disputed"), Decimal("0"))
        paid = sum((_d(p["amount"]) for p in allocated), Decimal("0"))
        pay_feed_ok = payments_feed is not None and payments_feed > deadline
        if liability is not None and liability > 0:
            applicable["payment"] = True
            shortfall = liability - paid
            if shortfall > liability * _d(th["payment_tolerance"]):
                confidence = 0.9 if pay_feed_ok else 0.35
                safeguards = [
                    {"check": "payments_feed_freshness", "result": "pass" if pay_feed_ok else "fail",
                     "detail": f"Payments feed extracted {feeds.get('payments') or 'never'}"},
                    {"check": "unallocated_payments", "result": "warn" if unallocated > 0 else "pass",
                     "detail": f"Unallocated {inputs['tax_type']} payments on record: {_money(unallocated)}"},
                    {"check": "disputes", "result": "warn" if disputed > 0 else "pass", "detail": f"Disputed amount: {_money(disputed)}"},
                ]
                action = "payment_follow_up"
                if unallocated >= shortfall or disputed >= shortfall:
                    confidence = min(confidence, 0.4)
                    action = "correct_data"
                ratio = float(shortfall / liability)
                signals.append(_signal(
                    "PAY-001", 40 + 60 * min(1.0, ratio), confidence,
                    f"Allocated payments {_money(paid)} are below declared liability {_money(liability)} for {ob['period']} "
                    f"(shortfall {_money(shortfall)}).",
                    exposure=shortfall, obligation_id=ob["id"],
                    evidence={"obligation": ob["id"], "return": latest["id"], "payments": [p["id"] for p in allocated], "legal_rule": legal},
                    safeguards=safeguards, action=action,
                ))
            elif allocated:
                last_paid = max(date.fromisoformat(p["payment_date"]) for p in allocated)
                days = (last_paid - deadline).days
                if days > 0:
                    signals.append(_signal(
                        "PAY-002", min(45, 15 + days / 2), 0.9,
                        f"Liability for {ob['period']} settled {days} day(s) after the deadline.",
                        obligation_id=ob["id"], evidence={"obligation": ob["id"], "payments": [p["id"] for p in allocated]},
                        action="educational_communication",
                    ))
        elif liability is None and not allocated:
            # Not filed and nothing paid. Exposure estimated from the taxpayer's own history only.
            applicable["payment"] = True
            hist = [
                _d(max(returns_by_period[h], key=lambda r: r["filing_date"])["reported_amount"])
                for h in _history_periods(ob["period"], 12 if len(ob["period"]) == 7 else 2)
                if h in returns_by_period
            ]
            estimate = _d(statistics.median(hist)) if hist else Decimal("0")
            signals.append(_signal(
                "PAY-003", 70, (0.7 if hist else 0.5) if pay_feed_ok else 0.3,
                f"No return and no payment recorded for {ob['period']}."
                + (f" Estimated exposure from the taxpayer's own filing history: {_money(estimate)}." if hist else
                   " No filing history, so exposure is not estimated."),
                exposure=estimate, obligation_id=ob["id"],
                evidence={"obligation": ob["id"], "history_periods_used": len(hist), "legal_rule": legal},
                safeguards=[{"check": "payments_feed_freshness", "result": "pass" if pay_feed_ok else "fail"}],
                action="filing_reminder",
            ))

    # --- Reporting (income deviation, hypothesis only) -----------------------------------------
    scope_periods = sorted({ob["period"] for ob in inputs["obligations"]})
    for period in scope_periods:
        rets = returns_by_period.get(period)
        if not rets:
            continue
        hist_periods = _history_periods(period, 6 if len(period) == 7 else 2)
        hist = [max(returns_by_period[h], key=lambda r: r["filing_date"]) for h in hist_periods if h in returns_by_period]
        if len(hist) < (3 if len(period) == 7 else 1):
            continue
        applicable["reporting"] = True
        current = max(rets, key=lambda r: r["filing_date"])
        baseline = _d(statistics.median([_d(h["reported_income"]) for h in hist]))
        if baseline <= 0:
            continue
        cur_income = _d(current["reported_income"])
        drop = float((baseline - cur_income) / baseline)
        if drop <= th["income_deviation_pct"]:
            continue
        safeguards = [{"check": "business_closure", "result": "warn" if tp["closed_on"] or tp["operating_status"] != "active" else "pass",
                       "detail": f"Operating status {tp['operating_status']}"}]
        confidence = 0.55
        if len(period) == 7:
            same_month_ly = f"{int(period[:4]) - 1}{period[4:]}"
            ly = returns_by_period.get(same_month_ly)
            if ly:
                ly_prior = [max(returns_by_period[h], key=lambda r: r["filing_date"]) for h in _history_periods(same_month_ly, 6) if h in returns_by_period]
                if ly_prior:
                    ly_base = _d(statistics.median([_d(h["reported_income"]) for h in ly_prior]))
                    ly_drop = float((ly_base - _d(max(ly, key=lambda r: r["filing_date"])["reported_income"])) / ly_base) if ly_base > 0 else 0
                    seasonal = ly_drop > th["income_deviation_pct"] * 0.75
                    safeguards.append({"check": "seasonality", "result": "warn" if seasonal else "pass",
                                       "detail": f"Same month last year declined {ly_drop:.0%} vs its baseline"})
                    if seasonal:
                        continue
            else:
                safeguards.append({"check": "seasonality", "result": "unknown", "detail": "No same-month history"})
        if safeguards[0]["result"] == "warn":
            confidence = 0.35
        rates = [_d(h["reported_amount"]) / _d(h["reported_income"]) for h in hist if _d(h["reported_income"]) > 0]
        eff_rate = _d(statistics.median(rates)) if rates else Decimal("0")
        exposure = max(Decimal("0"), (baseline - cur_income) * eff_rate)
        signals.append(_signal(
            "REP-001", min(80, 30 + 100 * (drop - th["income_deviation_pct"])), confidence,
            f"Reported income for {period} ({_money(cur_income)}) is {drop:.0%} below the taxpayer's recent median "
            f"({_money(baseline)}). Treat as a hypothesis to verify, not a finding.",
            exposure=exposure, evidence={"return": current["id"], "baseline_returns": [h["id"] for h in hist]},
            safeguards=safeguards, action="desk_verification", hypothesis=True,
        ))

    # --- Aggregate --------------------------------------------------------------------------------
    by_dim: dict[str, list[dict]] = {d: [] for d in DIMENSIONS}
    for s in signals:
        by_dim[s["dimension"]].append(s)
    dimension_scores: dict[str, float | None] = {}
    for d in DIMENSIONS:
        if not applicable[d] and not by_dim[d]:
            dimension_scores[d] = None
            continue
        sev = sorted((s["severity"] for s in by_dim[d]), reverse=True)
        dimension_scores[d] = round(min(100.0, sev[0] + 5 * (len(sev) - 1)), 2) if sev else 0.0
    active = {d: weights.get(d, 0.0) for d, v in dimension_scores.items() if v is not None and weights.get(d, 0.0) > 0}
    total_w = sum(active.values())
    weights_applied = {d: round(w / total_w, 6) for d, w in active.items()} if total_w else {}
    score = round(sum(dimension_scores[d] * w for d, w in weights_applied.items()), 2)

    # Data confidence (independent of risk)
    present = [k for k in ("taxpayers", "returns", "payments") if feeds.get(k)]
    coverage = round(len(present) / 3, 3)
    stale_days = th["feed_staleness_days"]
    tl = []
    for k in ("returns", "payments"):
        f = _date(feeds.get(k))
        if f is None:
            tl.append(0.0)
        else:
            age = (as_of - f).days
            tl.append(1.0 if age <= stale_days else max(0.0, 1 - (age - stale_days) / stale_days))
    timeliness = round(sum(tl) / len(tl), 3)
    ident = inputs["identity"]
    matching = ident["min_match_confidence"] if ident["identifier_count"] else 0.3
    merge_conf = ident["pending_merge_confidence"]
    if merge_conf is not None:
        matching = min(matching, 0.5)
    reliability = round(sum(s["confidence"] for s in signals) / len(signals), 3) if signals else 1.0
    components = {"coverage": coverage, "timeliness": timeliness, "matching_certainty": round(matching, 3),
                  "evidence_reliability": reliability}
    confidence = round(sum(components.values()) / 4, 3)
    # Critical-deficiency gate: one near-zero component (e.g. feeds far past staleness) must not be
    # averaged away by the others.
    if min(components.values()) < CRITICAL_COMPONENT:
        confidence = min(confidence, CRITICAL_CAP)

    exposure = sum((_d(s["exposure"]) for s in signals), Decimal("0"))
    reason_codes = sorted({s["reason_code"] for s in signals})
    flagged = score >= th["alert_score"] or any(
        s["severity"] >= th["alert_signal_severity"] and s["confidence"] >= th["min_confidence"] for s in signals
    )
    likely_duplicate = merge_conf is not None and merge_conf >= 0.9
    suppressed = flagged and (confidence < th["min_confidence"] or likely_duplicate)
    if not suppressed:
        suppression_reason = None
    elif likely_duplicate:
        suppression_reason = (f"Unresolved likely duplicate identity (match confidence {merge_conf:.2f}); "
                              "resolve the merge candidate before any adverse action")
    else:
        suppression_reason = (f"Data confidence {confidence:.2f} below minimum {th['min_confidence']:.2f}; "
                              "refer for data verification")
    return {
        "signals": signals,
        "dimension_scores": dimension_scores,
        "weights_applied": weights_applied,
        "score": score,
        "confidence": confidence,
        "confidence_components": components,
        "exposure_estimate": _money(exposure),
        "reason_codes": reason_codes,
        "flagged": flagged,
        "suppressed": suppressed,
        "suppression_reason": suppression_reason,
    }


def output_hash(result: dict[str, Any]) -> str:
    return sha256_json(result)


# ---------------------------------------------------------------------------------------------
# 3. Risk run orchestration
# ---------------------------------------------------------------------------------------------


def approved_model(db: Session, tenant_id: uuid.UUID) -> RiskModel | None:
    return db.execute(
        select(RiskModel).where(RiskModel.tenant_id == tenant_id, RiskModel.status == "approved").order_by(RiskModel.version.desc())
    ).scalars().first()


def execute_run(db: Session, run_id: uuid.UUID) -> RiskRun:
    run = db.get(RiskRun, run_id)
    tenant = db.get(Tenant, run.tenant_id)
    model = db.get(RiskModel, run.model_id)
    run.status, run.started_at = "running", datetime.now(timezone.utc)
    db.flush()

    obligation_engine.generate(db, tenant.id, run.tax_type, run.period, run.as_of)
    feeds = feed_freshness(db, tenant.id)
    rule_codes = {r.id: r.rule_code for r in db.execute(select(LegalRule).where(LegalRule.tenant_id == tenant.id)).scalars()}
    candidates = set(
        tid for (tid,) in db.execute(
            select(TaxObligation.taxpayer_id).where(TaxObligation.tenant_id == tenant.id, TaxObligation.tax_type == run.tax_type)
        )
    )
    taxpayers = list(
        db.execute(
            select(Taxpayer).where(Taxpayer.tenant_id == tenant.id, Taxpayer.merged_into_id.is_(None), Taxpayer.deleted_at.is_(None))
        ).scalars()
    )
    previous = {
        a.taxpayer_id: a
        for a in db.execute(
            select(RiskAssessment).where(
                RiskAssessment.tenant_id == tenant.id, RiskAssessment.tax_type == run.tax_type,
                RiskAssessment.period == run.period, RiskAssessment.superseded_by_id.is_(None),
                RiskAssessment.run_id != run.id,
            )
        ).scalars()
    }
    open_alerts = {
        a.taxpayer_id: a
        for a in db.execute(
            select(Alert).where(Alert.tenant_id == tenant.id, Alert.tax_type == run.tax_type, Alert.period == run.period,
                                Alert.status.in_(["open", "data_verification"]))
        ).scalars()
    }
    now = datetime.now(timezone.utc)
    input_hashes = []
    assessed = alerts = suppressed = 0
    for tp in sorted(taxpayers, key=lambda t: str(t.id)):
        if tp.id not in candidates and tp.registration_status != "unregistered":
            continue
        inputs = build_inputs(db, tenant, tp, run.tax_type, run.period, run.as_of, feeds, rule_codes)
        result = evaluate(inputs, model.weights, model.thresholds)
        ihash = sha256_json(inputs)
        input_hashes.append(ihash)
        a = RiskAssessment(
            tenant_id=tenant.id, run_id=run.id, taxpayer_id=tp.id, tax_type=run.tax_type, period=run.period,
            model_version=model.version, ruleset_version=ENGINE_VERSION,
            obligation_versions={o["period"]: f"{o['rule_code']}@v{o['rule_version']}" for o in inputs["obligations"]},
            evaluation_time=now, inputs=inputs, inputs_hash=ihash, output_hash=output_hash(result),
            weights_applied=result["weights_applied"], dimension_scores=result["dimension_scores"], score=result["score"],
            confidence=result["confidence"], confidence_components=result["confidence_components"],
            exposure_estimate=_d(result["exposure_estimate"]), reason_codes=result["reason_codes"],
            suppressed=result["suppressed"], suppression_reason=result["suppression_reason"],
        )
        db.add(a)
        db.flush()
        for s in result["signals"]:
            db.add(RiskSignal(
                tenant_id=tenant.id, assessment_id=a.id, run_id=run.id, taxpayer_id=tp.id,
                obligation_id=uuid.UUID(s["obligation_id"]) if s["obligation_id"] else None, rule_id=s["rule_id"],
                dimension=s["dimension"], severity=s["severity"], confidence=s["confidence"], exposure=_d(s["exposure"]),
                reason_code=s["reason_code"], explanation=s["explanation"], is_hypothesis=s["is_hypothesis"],
                evidence_ref=s["evidence_ref"], safeguards=s["safeguards"], recommended_action=s["recommended_action"],
            ))
        if (prev := previous.get(tp.id)) is not None:
            prev.superseded_by_id = a.id
        assessed += 1
        existing = open_alerts.get(tp.id)
        if result["flagged"]:
            status = "data_verification" if result["suppressed"] else "open"
            suppressed += int(result["suppressed"])
            if existing is not None:
                existing.assessment_id, existing.priority, existing.status = a.id, result["score"], status
            else:
                db.add(Alert(tenant_id=tenant.id, assessment_id=a.id, taxpayer_id=tp.id, tax_type=run.tax_type,
                             period=run.period, status=status, priority=result["score"]))
                alerts += 1
        elif existing is not None:
            existing.assessment_id, existing.status = a.id, "dismissed"
            existing.triage_reason = "Auto-closed: superseding assessment no longer meets alert criteria"
            existing.triaged_at = now
    run.dataset_hash = sha256_json(sorted(input_hashes))
    run.assessed, run.alerts_created, run.suppressed = assessed, alerts, suppressed
    run.status, run.completed_at = "completed", datetime.now(timezone.utc)
    audit.record(
        db, tenant_id=tenant.id, actor_id=run.requested_by, action="risk_run.completed", resource_type="risk_run",
        resource_id=run.id, details={"assessed": assessed, "alerts_created": alerts, "suppressed": suppressed,
                                     "model_version": model.version, "dataset_hash": run.dataset_hash},
    )
    db.flush()
    return run


def reproduce(assessment: RiskAssessment, model: RiskModel) -> dict[str, Any]:
    """Re-evaluate stored frozen inputs with the recorded model version (PRD §16)."""
    result = evaluate(assessment.inputs, model.weights, model.thresholds)
    h = output_hash(result)
    return {
        "assessment_id": str(assessment.id),
        "inputs_hash_verified": sha256_json(assessment.inputs) == assessment.inputs_hash,
        "stored_output_hash": assessment.output_hash,
        "recomputed_output_hash": h,
        "reproducible": h == assessment.output_hash and sha256_json(assessment.inputs) == assessment.inputs_hash,
        "score": result["score"],
    }
