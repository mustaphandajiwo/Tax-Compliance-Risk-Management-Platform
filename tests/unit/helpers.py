"""Builders for engine fact records used by unit tests."""

from __future__ import annotations

import copy
from typing import Any

BASE_FACTS: dict[str, Any] = {
    "anchor_period": False,
    "obligation_status": "active",
    "return_due_at": "2026-07-15T22:59:59+00:00",
    "payment_due_at": "2026-07-10T22:59:59+00:00",
    "return_due_passed": True,
    "payment_due_passed": True,
    "extension_active": False,
    "extension_pending": False,
    "accepted_filing_count": 0,
    "accepted_at": None,
    "filing_late_days": None,
    "submission_pending": False,
    "processing_window_open": False,
    "rejected_uncorrected": False,
    "declared_payable": None,
    "paid_allocated_total": 0.0,
    "credits_adjustments_total": 0.0,
    "residual_amount": None,
    "settled_payment_count": 0,
    "first_payment_at": None,
    "payment_late_days": None,
    "reversed_payment_count": 0,
    "reversal_pending": False,
    "possible_unallocated_receipt": False,
    "bank_delay_dispute": False,
    "quarantined_period_records": False,
    "source_conflict": False,
    "legal_hold": False,
    "disputed": False,
}


def employer_period(
    period: str = "2026-06", history: dict[str, list] | None = None, **overrides: Any
) -> dict:
    facts = copy.deepcopy(BASE_FACTS)
    quality = {
        "identity_verified": True,
        "match_confidence": 1.0,
        "staleness_days": 2,
        "freshness_sla_days": 7,
        "coverage": {"filing": True, "payment": True},
    }
    for k, v in overrides.items():
        if k in quality:
            quality[k] = v
        else:
            assert k in facts, k
            facts[k] = v
    return {
        "kind": "employer_period",
        "subject_type": "employer",
        "subject_id": "NGS-DEMO-EMP-0001",
        "period": period,
        "tax_type": "PAYE",
        "facts": facts,
        "quality": quality,
        "history": history or {"filing": [], "payment": []},
        "evidence": {
            "_subject": ["src:employer:NGS-DEMO-EMP-0001"],
            "accepted_filing_count": ["coverage:ngsirs_paye_return:2026-06"],
        },
    }


def assessment(**overrides: Any) -> dict:
    facts = {
        "assessment_status": "served",
        "served": True,
        "due_date": "2026-05-31",
        "due_passed": True,
        "appeal_status": "none",
        "outstanding_amount": 350000.0,
        "assessed_amount": 350000.0,
        "employer_ref": "NGS-DEMO-EMP-0001",
        "legal_hold": False,
        "disputed": False,
    }
    facts.update(overrides)
    return {
        "kind": "assessment",
        "subject_type": "assessment",
        "subject_id": "NGS-DEMO-ASM-0001",
        "period": "2026-02",
        "tax_type": "PAYE",
        "facts": facts,
        "quality": {
            "identity_verified": True,
            "match_confidence": 1.0,
            "staleness_days": 1,
            "freshness_sla_days": 7,
            "coverage": {"assessment": True},
        },
        "evidence": {"outstanding_amount": ["src:assessment:NGS-DEMO-ASM-0001"]},
    }
