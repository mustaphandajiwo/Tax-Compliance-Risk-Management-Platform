"""Treatment catalogue and decision matrix (PRD section 12).

Every treatment names the human gate that must approve it. Nothing here sends
anything: a treatment is a recommendation that a case workflow may adopt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Treatment:
    code: str
    label: str
    pathway: str
    human_gate: str  # role that must approve
    outward: bool  # involves taxpayer contact if approved
    approver_roles: tuple[str, ...]


TREATMENTS: dict[str, Treatment] = {
    t.code: t
    for t in [
        Treatment(
            "internal_correction",
            "Internal data correction",
            "Technical data error",
            "Data steward",
            False,
            ("data_steward",),
        ),
        Treatment(
            "review_then_approved_reminder",
            "Review, then approved reminder",
            "Low-risk verified missed filing",
            "Approved outbound communication rules",
            True,
            ("compliance_manager",),
        ),
        Treatment(
            "targeted_assistance",
            "Targeted taxpayer assistance",
            "Repeated verified late filing",
            "Compliance officer",
            True,
            ("compliance_manager",),
        ),
        Treatment(
            "compliance_engagement",
            "Compliance engagement",
            "Repeated verified missed filing",
            "Compliance officer",
            True,
            ("compliance_manager",),
        ),
        Treatment(
            "payment_engagement",
            "Payment engagement",
            "Verified late or short remittance",
            "Compliance officer",
            True,
            ("compliance_manager",),
        ),
        Treatment(
            "desk_clarification",
            "Request clarification / desk review",
            "Material reporting discrepancy",
            "Manager approval",
            True,
            ("compliance_manager",),
        ),
        Treatment(
            "treasury_reconciliation",
            "Treasury / payment reconciliation",
            "Payment may exist but is unmatched",
            "Data steward",
            False,
            ("data_steward",),
        ),
        Treatment(
            "debt_reconciliation",
            "Reconciliation / lawful debt process",
            "Confirmed assessed arrears",
            "Officer + legal rules",
            True,
            ("compliance_manager", "legal_approver"),
        ),
        Treatment(
            "audit_referral",
            "Evidence review then audit referral",
            "Potential audit candidate",
            "Authorised audit selection",
            False,
            ("audit_officer", "compliance_manager"),
        ),
        Treatment(
            "identity_review",
            "Identity / duplicate review",
            "Technical data error",
            "Data steward",
            False,
            ("data_steward",),
        ),
        Treatment(
            "source_reconciliation",
            "Source reconciliation; suppress adverse action",
            "Uncertain obligation / disputed status",
            "Data steward",
            False,
            ("data_steward",),
        ),
        Treatment(
            "legal_review",
            "Investigate and pause automated action",
            "Uncertain obligation / disputed status",
            "Legal or specialist review",
            False,
            ("legal_approver",),
        ),
    ]
}


def allowed_next_action(signal_class: str, data_hold: bool, legal_hold: bool, disputed: bool) -> str:
    if data_hold:
        return "data_review"
    if legal_hold or disputed:
        return "internal_review_only"
    if signal_class == "data_quality":
        return "internal_reconciliation"
    return "internal_review"
