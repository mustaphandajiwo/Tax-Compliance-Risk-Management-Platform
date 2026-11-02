"""Role-based access with deny-by-default (PRD section 6).

Each permission lists the roles that hold it. Anything not listed is denied.
Segregation-of-duties checks (maker != checker) live next to the operations
that need them, because they depend on who did the earlier step.
"""

from __future__ import annotations

ROLES = {
    "platform_admin": "State platform administrator",
    "legal_approver": "Legal / policy approver",
    "risk_analyst": "Risk analyst",
    "compliance_manager": "Compliance manager",
    "compliance_officer": "Compliance officer",
    "audit_officer": "Audit officer",
    "data_steward": "Data steward",
    "executive_viewer": "Executive / reporting viewer",
    "integration_client": "System integration (machine client)",
}

OPERATIONAL = ("risk_analyst", "compliance_manager", "compliance_officer", "audit_officer")

PERMISSIONS: dict[str, tuple[str, ...]] = {
    "imports:read": ("data_steward", "platform_admin", "risk_analyst", "compliance_manager"),
    "ingest:push": ("integration_client", "data_steward"),
    "connectors:run": ("data_steward", "platform_admin"),
    "imports:create": ("data_steward", "platform_admin"),
    "imports:commit": ("data_steward",),
    "imports:rollback": ("data_steward",),
    "quality:read": ("data_steward", "risk_analyst", "compliance_manager", "platform_admin"),
    "quality:resolve": ("data_steward",),
    "identity:review": ("data_steward",),
    "legal:read": (
        "legal_approver",
        "risk_analyst",
        "compliance_manager",
        "compliance_officer",
        "audit_officer",
        "data_steward",
        "platform_admin",
    ),
    "legal:draft": ("legal_approver", "risk_analyst", "platform_admin"),
    "legal:approve": ("legal_approver",),
    "rules:read": ("risk_analyst", "compliance_manager", "legal_approver", "audit_officer", "platform_admin"),
    "rules:draft": ("risk_analyst",),
    "rules:backtest": ("risk_analyst", "compliance_manager"),
    "rules:approve": ("compliance_manager", "legal_approver"),
    "rules:activate": ("compliance_manager",),
    "evaluations:run_shadow": ("risk_analyst", "compliance_manager"),
    "evaluations:run_operational": ("compliance_manager",),
    "evaluations:read": ("risk_analyst", "compliance_manager", "audit_officer", "data_steward"),
    "risks:read": (*OPERATIONAL, "data_steward", "legal_approver"),
    "risks:review": ("risk_analyst", "compliance_officer", "compliance_manager", "data_steward"),
    "risks:override": ("compliance_manager",),
    "risks:legal_hold": ("legal_approver", "compliance_manager"),
    "taxpayers:read": (*OPERATIONAL, "data_steward"),
    "taxpayers:reveal_identifiers": ("data_steward", "audit_officer"),
    "cases:read": (*OPERATIONAL, "legal_approver"),
    "cases:create": ("risk_analyst", "compliance_officer", "compliance_manager", "data_steward"),
    "cases:approve": ("compliance_manager", "data_steward"),  # treatment approver_roles narrow this further
    "cases:assign": ("compliance_manager",),
    "cases:act": ("compliance_officer", "compliance_manager", "audit_officer", "data_steward"),
    "cases:close": ("compliance_manager", "compliance_officer", "data_steward"),
    "cases:audit_referral": ("compliance_manager",),
    "evidence:export": ("compliance_manager", "audit_officer"),
    "dashboard:read": (*OPERATIONAL, "executive_viewer", "data_steward", "legal_approver", "platform_admin"),
    "reports:read": ("compliance_manager", "risk_analyst", "executive_viewer", "audit_officer"),
    "reports:export": ("compliance_manager", "executive_viewer", "audit_officer"),
    "programmes:read": ("compliance_manager", "risk_analyst", "executive_viewer", "compliance_officer"),
    "programmes:manage": ("compliance_manager", "risk_analyst"),
    "programmes:approve": ("compliance_manager",),
    "audit:read": ("audit_officer", "platform_admin", "legal_approver"),
    "admin:users": ("platform_admin",),
    "admin:retention": ("platform_admin",),
    "ops:read": ("platform_admin", "data_steward", "risk_analyst"),
    "reference:read": tuple(r for r in ROLES if r != "integration_client"),
}

# Purposes a request must declare (X-Purpose) for sensitive reads or exports.
PURPOSES = {
    "case_review": "Reviewing an assigned compliance case",
    "desk_review": "Approved desk-review workflow",
    "audit": "Authorised audit work",
    "data_quality": "Resolving data-quality and identity issues",
    "management_reporting": "Aggregated management reporting",
}


def has_permission(roles: list[str] | tuple[str, ...], permission: str) -> bool:
    allowed = PERMISSIONS.get(permission)
    if allowed is None:
        return False
    return any(r in allowed for r in roles)


def permissions_for(roles: list[str]) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(roles, p))
