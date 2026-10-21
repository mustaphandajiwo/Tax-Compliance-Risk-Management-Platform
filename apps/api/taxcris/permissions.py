"""Role → permission matrix (PRD §2).

Approval limits that depend on *who* did the earlier step (four-eyes, "cannot approve own") are
enforced in the domain layer, not here: holding ``*.approve`` is necessary but not sufficient.
"""

from enum import StrEnum


class Role(StrEnum):
    STATE_ADMIN = "state_admin"
    DATA_STEWARD = "data_steward"
    RISK_ANALYST = "risk_analyst"
    COMPLIANCE_OFFICER = "compliance_officer"
    COMPLIANCE_MANAGER = "compliance_manager"
    AUDIT_MANAGER = "audit_manager"
    LEGAL_OFFICER = "legal_officer"
    EXECUTIVE = "executive"
    SECURITY_AUDITOR = "security_auditor"


class P(StrEnum):
    TENANT_ADMIN = "tenant.admin"
    USERS_MANAGE = "users.manage"
    USERS_READ = "users.read"
    IMPORTS_CREATE = "imports.create"
    IMPORTS_READ = "imports.read"
    DATA_QUALITY_REVIEW = "data_quality.review"
    MERGES_PROPOSE = "merges.propose"
    MERGES_APPROVE = "merges.approve"
    TAXPAYERS_READ = "taxpayers.read"
    TAXPAYERS_READ_SENSITIVE = "taxpayers.read_sensitive"
    LEGAL_RULES_READ = "legal_rules.read"
    LEGAL_RULES_DRAFT = "legal_rules.draft"
    LEGAL_RULES_APPROVE = "legal_rules.approve"
    RISK_MODELS_DRAFT = "risk_models.draft"
    RISK_MODELS_APPROVE = "risk_models.approve"
    RISK_RUNS_CREATE = "risk_runs.create"
    RISK_READ = "risk.read"
    ALERTS_TRIAGE = "alerts.triage"
    CASES_READ = "cases.read"
    CASES_CREATE = "cases.create"
    CASES_PROPOSE = "cases.propose"
    CASES_WORK = "cases.work"
    CASES_APPROVE = "cases.approve"
    AUDITS_DECIDE = "audits.decide"
    METRICS_READ = "metrics.read"
    EXPORTS_AGGREGATE = "exports.aggregate"
    EXPORTS_RECORDS = "exports.records"
    AUDIT_LOG_READ = "audit_log.read"


ROLE_PERMISSIONS: dict[Role, frozenset[P]] = {
    Role.STATE_ADMIN: frozenset(
        {P.TENANT_ADMIN, P.USERS_MANAGE, P.USERS_READ, P.IMPORTS_READ, P.LEGAL_RULES_READ, P.METRICS_READ}
    ),
    Role.DATA_STEWARD: frozenset(
        {
            P.IMPORTS_CREATE,
            P.IMPORTS_READ,
            P.DATA_QUALITY_REVIEW,
            P.MERGES_PROPOSE,
            P.MERGES_APPROVE,
            P.TAXPAYERS_READ,
            P.TAXPAYERS_READ_SENSITIVE,
            P.METRICS_READ,
        }
    ),
    Role.RISK_ANALYST: frozenset(
        {
            P.IMPORTS_READ,
            P.TAXPAYERS_READ,
            P.LEGAL_RULES_READ,
            P.RISK_MODELS_DRAFT,
            P.RISK_MODELS_APPROVE,
            P.RISK_RUNS_CREATE,
            P.RISK_READ,
            P.ALERTS_TRIAGE,
            P.CASES_READ,
            P.CASES_CREATE,
            P.CASES_PROPOSE,
            P.METRICS_READ,
            P.EXPORTS_RECORDS,
            P.USERS_READ,
        }
    ),
    Role.COMPLIANCE_OFFICER: frozenset(
        {P.TAXPAYERS_READ, P.LEGAL_RULES_READ, P.RISK_READ, P.CASES_READ, P.CASES_PROPOSE, P.CASES_WORK, P.METRICS_READ}
    ),
    Role.COMPLIANCE_MANAGER: frozenset(
        {
            P.TAXPAYERS_READ,
            P.LEGAL_RULES_READ,
            P.RISK_READ,
            P.RISK_MODELS_APPROVE,
            P.RISK_RUNS_CREATE,
            P.ALERTS_TRIAGE,
            P.CASES_READ,
            P.CASES_CREATE,
            P.CASES_PROPOSE,
            P.CASES_APPROVE,
            P.METRICS_READ,
            P.EXPORTS_AGGREGATE,
            P.EXPORTS_RECORDS,
            P.USERS_READ,
        }
    ),
    Role.AUDIT_MANAGER: frozenset(
        {P.TAXPAYERS_READ, P.LEGAL_RULES_READ, P.RISK_READ, P.CASES_READ, P.AUDITS_DECIDE, P.METRICS_READ, P.USERS_READ}
    ),
    Role.LEGAL_OFFICER: frozenset({P.LEGAL_RULES_READ, P.LEGAL_RULES_DRAFT, P.LEGAL_RULES_APPROVE, P.METRICS_READ}),
    Role.EXECUTIVE: frozenset({P.METRICS_READ, P.EXPORTS_AGGREGATE}),
    Role.SECURITY_AUDITOR: frozenset({P.AUDIT_LOG_READ, P.USERS_READ}),
}


def permissions_for(role: str) -> frozenset[P]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()
