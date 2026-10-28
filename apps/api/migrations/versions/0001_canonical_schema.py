"""canonical schema

Revision ID: 0001
Revises:
Create Date: 2026-10-28 03:26:00.067260
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS ingest_batch_seq")
    op.create_table(
        "tenant",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hosting_mode", sa.String(length=32), nullable=False),
        sa.Column("legal_config_version", sa.String(length=64), nullable=True),
        sa.Column("is_test_only", sa.Boolean(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("roles", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("lga_scope", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("allowed_purposes", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "username"),
    )
    op.create_index(op.f("ix_app_user_tenant_id"), "app_user", ["tenant_id"], unique=False)
    op.create_table(
        "assessment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("natural_key", sa.String(length=200), nullable=False),
        sa.Column("assessment_ref", sa.String(length=64), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("assessment_type", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("served_on", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("appeal_status", sa.String(length=32), nullable=False),
        sa.Column("outstanding_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_assessment_batch_id"), "assessment", ["batch_id"], unique=False)
    op.create_index(op.f("ix_assessment_employer_id"), "assessment", ["employer_id"], unique=False)
    op.create_index(op.f("ix_assessment_is_current"), "assessment", ["is_current"], unique=False)
    op.create_index(op.f("ix_assessment_natural_key"), "assessment", ["natural_key"], unique=False)
    op.create_index(op.f("ix_assessment_tenant_id"), "assessment", ["tenant_id"], unique=False)
    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("actor_roles", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("subject_ref", sa.String(length=200), nullable=True),
        sa.Column("purpose", sa.String(length=80), nullable=True),
        sa.Column("before_hash", sa.String(length=64), nullable=True),
        sa.Column("after_hash", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "seq"),
    )
    op.create_index(op.f("ix_audit_event_event_type"), "audit_event", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_event_subject_ref"), "audit_event", ["subject_ref"], unique=False)
    op.create_index(op.f("ix_audit_event_tenant_id"), "audit_event", ["tenant_id"], unique=False)
    op.create_table(
        "data_source",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("feed_types", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("system_of_record", sa.Boolean(), nullable=False),
        sa.Column("data_sharing_basis", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("permitted_purpose", sa.Text(), nullable=False),
        sa.Column("freshness_sla_days", sa.Integer(), nullable=False),
        sa.Column("is_external", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_name"),
    )
    op.create_index(op.f("ix_data_source_tenant_id"), "data_source", ["tenant_id"], unique=False)
    op.create_table(
        "employer",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_employer_id", sa.String(length=64), nullable=False),
        sa.Column("linked_taxpayer_ref", sa.String(length=64), nullable=True),
        sa.Column("taxpayer_id", sa.UUID(), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("activity_from", sa.Date(), nullable=True),
        sa.Column("activity_to", sa.Date(), nullable=True),
        sa.Column("office_code", sa.String(length=32), nullable=True),
        sa.Column("lga_code", sa.String(length=16), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("segment", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_employer_batch_id"), "employer", ["batch_id"], unique=False)
    op.create_index(op.f("ix_employer_is_current"), "employer", ["is_current"], unique=False)
    op.create_index(op.f("ix_employer_source_employer_id"), "employer", ["source_employer_id"], unique=False)
    op.create_index(op.f("ix_employer_taxpayer_id"), "employer", ["taxpayer_id"], unique=False)
    op.create_index(op.f("ix_employer_tenant_id"), "employer", ["tenant_id"], unique=False)
    op.create_table(
        "extension",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("natural_key", sa.String(length=200), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=False),
        sa.Column("obligation_type", sa.String(length=64), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("new_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_extension_batch_id"), "extension", ["batch_id"], unique=False)
    op.create_index(op.f("ix_extension_employer_id"), "extension", ["employer_id"], unique=False)
    op.create_index(op.f("ix_extension_is_current"), "extension", ["is_current"], unique=False)
    op.create_index(op.f("ix_extension_natural_key"), "extension", ["natural_key"], unique=False)
    op.create_index(op.f("ix_extension_tenant_id"), "extension", ["tenant_id"], unique=False)
    op.create_table(
        "idempotency_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "actor_id", "key"),
    )
    op.create_index(
        op.f("ix_idempotency_record_tenant_id"), "idempotency_record", ["tenant_id"], unique=False
    )
    op.create_table(
        "identity_match",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("taxpayer_id", sa.UUID(), nullable=True),
        sa.Column("match_type", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_identity_match_employer_id"), "identity_match", ["employer_id"], unique=False)
    op.create_index(op.f("ix_identity_match_tenant_id"), "identity_match", ["tenant_id"], unique=False)
    op.create_table(
        "input_snapshot",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("batch_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("facts_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("period_from", sa.String(length=7), nullable=False),
        sa.Column("period_to", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_input_snapshot_tenant_id"), "input_snapshot", ["tenant_id"], unique=False)
    op.create_table(
        "legal_instrument",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("authority", sa.String(length=200), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index(op.f("ix_legal_instrument_tenant_id"), "legal_instrument", ["tenant_id"], unique=False)
    op.create_table(
        "lga",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("pilot", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index(op.f("ix_lga_tenant_id"), "lga", ["tenant_id"], unique=False)
    op.create_table(
        "payment",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("natural_key", sa.String(length=200), nullable=False),
        sa.Column("payment_reference", sa.String(length=64), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=True),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reversal_status", sa.String(length=32), nullable=False),
        sa.Column("settlement_status", sa.String(length=32), nullable=False),
        sa.Column("allocation_status", sa.String(length=32), nullable=False),
        sa.Column("bank_delay_dispute", sa.Boolean(), nullable=False),
        sa.Column("credit_adjustment", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payment_batch_id"), "payment", ["batch_id"], unique=False)
    op.create_index(op.f("ix_payment_employer_id"), "payment", ["employer_id"], unique=False)
    op.create_index(op.f("ix_payment_is_current"), "payment", ["is_current"], unique=False)
    op.create_index(op.f("ix_payment_natural_key"), "payment", ["natural_key"], unique=False)
    op.create_index(op.f("ix_payment_tenant_id"), "payment", ["tenant_id"], unique=False)
    op.create_table(
        "programme",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("population", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("denominator_definition", sa.Text(), nullable=False),
        sa.Column("baseline_from", sa.String(length=7), nullable=False),
        sa.Column("baseline_to", sa.String(length=7), nullable=False),
        sa.Column("evaluation_from", sa.String(length=7), nullable=False),
        sa.Column("evaluation_to", sa.String(length=7), nullable=False),
        sa.Column("intervention", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("resource_budget", sa.Text(), nullable=True),
        sa.Column("comparison_share", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("evaluation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_programme_tenant_id"), "programme", ["tenant_id"], unique=False)
    op.create_table(
        "retention_policy",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("data_class", sa.String(length=80), nullable=False),
        sa.Column("retain_days", sa.Integer(), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "data_class"),
    )
    op.create_index(op.f("ix_retention_policy_tenant_id"), "retention_policy", ["tenant_id"], unique=False)
    op.create_table(
        "return_filing",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("natural_key", sa.String(length=200), nullable=False),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=False),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("filing_reference", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_declared", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_return_filing_batch_id"), "return_filing", ["batch_id"], unique=False)
    op.create_index(op.f("ix_return_filing_employer_id"), "return_filing", ["employer_id"], unique=False)
    op.create_index(op.f("ix_return_filing_is_current"), "return_filing", ["is_current"], unique=False)
    op.create_index(op.f("ix_return_filing_natural_key"), "return_filing", ["natural_key"], unique=False)
    op.create_index(op.f("ix_return_filing_period_code"), "return_filing", ["period_code"], unique=False)
    op.create_index(op.f("ix_return_filing_tenant_id"), "return_filing", ["tenant_id"], unique=False)
    op.create_table(
        "rule_definition",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=16), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("catalogue_status", sa.String(length=32), nullable=False),
        sa.Column("legacy_codes", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("default_treatment", sa.String(length=64), nullable=True),
        sa.Column("active_version_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "rule_code"),
    )
    op.create_index(op.f("ix_rule_definition_tenant_id"), "rule_definition", ["tenant_id"], unique=False)
    op.create_table(
        "rule_version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=16), nullable=False),
        sa.Column("expression_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("legal_ref", sa.String(length=120), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("author_id", sa.String(length=100), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("backtest_report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("approvals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("activated_by", sa.String(length=100), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "rule_code", "version"),
    )
    op.create_index(op.f("ix_rule_version_rule_code"), "rule_version", ["rule_code"], unique=False)
    op.create_index(op.f("ix_rule_version_tenant_id"), "rule_version", ["tenant_id"], unique=False)
    op.create_table(
        "tax_obligation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("natural_key", sa.String(length=200), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("taxpayer_ref", sa.String(length=64), nullable=False),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("obligation_type", sa.String(length=64), nullable=False),
        sa.Column("legal_code", sa.String(length=80), nullable=False),
        sa.Column("statutory_version", sa.String(length=32), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("exemption_status", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tax_obligation_batch_id"), "tax_obligation", ["batch_id"], unique=False)
    op.create_index(op.f("ix_tax_obligation_employer_id"), "tax_obligation", ["employer_id"], unique=False)
    op.create_index(op.f("ix_tax_obligation_is_current"), "tax_obligation", ["is_current"], unique=False)
    op.create_index(op.f("ix_tax_obligation_natural_key"), "tax_obligation", ["natural_key"], unique=False)
    op.create_index(op.f("ix_tax_obligation_tenant_id"), "tax_obligation", ["tenant_id"], unique=False)
    op.create_table(
        "tax_office",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("lga_code", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index(op.f("ix_tax_office_tenant_id"), "tax_office", ["tenant_id"], unique=False)
    op.create_table(
        "taxpayer",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_taxpayer_id", sa.String(length=64), nullable=False),
        sa.Column("taxpayer_type", sa.String(length=32), nullable=False),
        sa.Column("legal_type", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("name_token", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=16), nullable=False),
        sa.Column("lga_code", sa.String(length=16), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("superseded_by_batch_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_taxpayer_batch_id"), "taxpayer", ["batch_id"], unique=False)
    op.create_index(op.f("ix_taxpayer_is_current"), "taxpayer", ["is_current"], unique=False)
    op.create_index(op.f("ix_taxpayer_source_taxpayer_id"), "taxpayer", ["source_taxpayer_id"], unique=False)
    op.create_index(op.f("ix_taxpayer_tenant_id"), "taxpayer", ["tenant_id"], unique=False)
    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("rule_set_hash", sa.String(length=64), nullable=False),
        sa.Column("rule_version_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("period_from", sa.String(length=7), nullable=False),
        sa.Column("period_to", sa.String(length=7), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome_digest", sa.String(length=64), nullable=True),
        sa.Column("triggered_by", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["input_snapshot.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_run_tenant_id"), "evaluation_run", ["tenant_id"], unique=False)
    op.create_table(
        "ingest_batch",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "seq", sa.BigInteger(), server_default=sa.text("nextval('ingest_batch_seq')"), nullable=False
        ),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("feed_type", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest_signature", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("coverage_from", sa.String(length=7), nullable=True),
        sa.Column("coverage_to", sa.String(length=7), nullable=True),
        sa.Column("coverage_lga", sa.String(length=16), nullable=True),
        sa.Column("qa_status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("quality_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("committed_by", sa.String(length=100), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", sa.String(length=100), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingest_batch_feed_type"), "ingest_batch", ["feed_type"], unique=False)
    op.create_index(op.f("ix_ingest_batch_tenant_id"), "ingest_batch", ["tenant_id"], unique=False)
    op.create_index(
        "uq_batch_content",
        "ingest_batch",
        ["tenant_id", "source_id", "feed_type", "content_hash"],
        unique=True,
        postgresql_where=sa.text("qa_status <> 'rolled_back'"),
    )
    op.create_table(
        "legal_rule_version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("obligation_type", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.UUID(), nullable=False),
        sa.Column("provision_ref", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("drafted_by", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["legal_instrument.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", "version"),
    )
    op.create_index(op.f("ix_legal_rule_version_code"), "legal_rule_version", ["code"], unique=False)
    op.create_index(
        op.f("ix_legal_rule_version_tenant_id"), "legal_rule_version", ["tenant_id"], unique=False
    )
    op.create_table(
        "payment_allocation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payment.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_allocation_employer_id"), "payment_allocation", ["employer_id"], unique=False
    )
    op.create_index(
        op.f("ix_payment_allocation_payment_id"), "payment_allocation", ["payment_id"], unique=False
    )
    op.create_index(
        op.f("ix_payment_allocation_tenant_id"), "payment_allocation", ["tenant_id"], unique=False
    )
    op.create_table(
        "programme_member",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("programme_id", sa.UUID(), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=False),
        sa.Column("group_name", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["programme_id"],
            ["programme.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("programme_id", "employer_id"),
    )
    op.create_index(
        op.f("ix_programme_member_programme_id"), "programme_member", ["programme_id"], unique=False
    )
    op.create_index(op.f("ix_programme_member_tenant_id"), "programme_member", ["tenant_id"], unique=False)
    op.create_table(
        "taxpayer_identifier",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("taxpayer_id", sa.UUID(), nullable=False),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("masked", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["taxpayer_id"],
            ["taxpayer.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_taxpayer_identifier_taxpayer_id"), "taxpayer_identifier", ["taxpayer_id"], unique=False
    )
    op.create_index(
        op.f("ix_taxpayer_identifier_tenant_id"), "taxpayer_identifier", ["tenant_id"], unique=False
    )
    op.create_index(op.f("ix_taxpayer_identifier_token"), "taxpayer_identifier", ["token"], unique=False)
    op.create_table(
        "period_schedule",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("obligation_type", sa.String(length=64), nullable=False),
        sa.Column("legal_code", sa.String(length=80), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legal_rule_version_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["legal_rule_version_id"],
            ["legal_rule_version.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "legal_code", "period_code"),
    )
    op.create_index(op.f("ix_period_schedule_tenant_id"), "period_schedule", ["tenant_id"], unique=False)
    op.create_table(
        "risk_finding",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("finding_ref", sa.String(length=40), nullable=False),
        sa.Column("finding_key", sa.String(length=200), nullable=False),
        sa.Column("rule_code", sa.String(length=16), nullable=False),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("rule_version", sa.String(length=16), nullable=False),
        sa.Column("legal_rule_version_id", sa.UUID(), nullable=True),
        sa.Column("legal_version_label", sa.String(length=120), nullable=True),
        sa.Column("tax_type", sa.String(length=32), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("signal_class", sa.String(length=32), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=True),
        sa.Column("lga_code", sa.String(length=16), nullable=True),
        sa.Column("period_code", sa.String(length=7), nullable=True),
        sa.Column("likelihood", sa.Integer(), nullable=True),
        sa.Column("consequence", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("priority_band", sa.String(length=32), nullable=True),
        sa.Column("priority_note", sa.String(length=64), nullable=True),
        sa.Column("effort", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_hold", sa.Boolean(), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False),
        sa.Column("disputed", sa.Boolean(), nullable=False),
        sa.Column("holds", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("treatment", sa.String(length=64), nullable=True),
        sa.Column("allowed_next_action", sa.String(length=64), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("alternative_explanations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("matched_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome_hash", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("first_run_id", sa.UUID(), nullable=False),
        sa.Column("last_seen_run_id", sa.UUID(), nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_run.id"],
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["input_snapshot.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_ref"),
    )
    op.create_index(op.f("ix_risk_finding_employer_id"), "risk_finding", ["employer_id"], unique=False)
    op.create_index(op.f("ix_risk_finding_employer_ref"), "risk_finding", ["employer_ref"], unique=False)
    op.create_index(op.f("ix_risk_finding_finding_key"), "risk_finding", ["finding_key"], unique=False)
    op.create_index(op.f("ix_risk_finding_lga_code"), "risk_finding", ["lga_code"], unique=False)
    op.create_index(op.f("ix_risk_finding_period_code"), "risk_finding", ["period_code"], unique=False)
    op.create_index(op.f("ix_risk_finding_rule_code"), "risk_finding", ["rule_code"], unique=False)
    op.create_index(op.f("ix_risk_finding_signal_class"), "risk_finding", ["signal_class"], unique=False)
    op.create_index(op.f("ix_risk_finding_status"), "risk_finding", ["status"], unique=False)
    op.create_index(op.f("ix_risk_finding_subject_id"), "risk_finding", ["subject_id"], unique=False)
    op.create_index(op.f("ix_risk_finding_tenant_id"), "risk_finding", ["tenant_id"], unique=False)
    op.create_index(
        "uq_finding_key_rule_version",
        "risk_finding",
        ["tenant_id", "finding_key", "rule_version_id"],
        unique=True,
    )
    op.create_table(
        "risk_signal",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=16), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reasons", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("data_confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_run.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_signal_run_id"), "risk_signal", ["run_id"], unique=False)
    op.create_index(op.f("ix_risk_signal_tenant_id"), "risk_signal", ["tenant_id"], unique=False)
    op.create_table(
        "source_coverage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("feed_type", sa.String(length=40), nullable=False),
        sa.Column("period_code", sa.String(length=7), nullable=False),
        sa.Column("scope_lga", sa.String(length=16), nullable=True),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("reconciled", sa.Boolean(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["ingest_batch.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_coverage_tenant_id"), "source_coverage", ["tenant_id"], unique=False)
    op.create_table(
        "source_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("feed_type", sa.String(length=40), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("natural_id", sa.String(length=200), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_codes", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("employer_ref", sa.String(length=100), nullable=True),
        sa.Column("resolution", sa.String(length=40), nullable=True),
        sa.Column("resolved_by", sa.String(length=100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["ingest_batch.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_record_batch_id"), "source_record", ["batch_id"], unique=False)
    op.create_index(op.f("ix_source_record_employer_ref"), "source_record", ["employer_ref"], unique=False)
    op.create_index(op.f("ix_source_record_natural_id"), "source_record", ["natural_id"], unique=False)
    op.create_index(op.f("ix_source_record_tenant_id"), "source_record", ["tenant_id"], unique=False)
    op.create_table(
        "case_record",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("case_ref", sa.String(length=40), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("finding_key", sa.String(length=200), nullable=False),
        sa.Column("employer_id", sa.UUID(), nullable=True),
        sa.Column("employer_ref", sa.String(length=64), nullable=True),
        sa.Column("treatment", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("assigned_to", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_days", sa.Integer(), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False),
        sa.Column("outward_permitted", sa.Boolean(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["risk_finding.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_ref"),
    )
    op.create_index(op.f("ix_case_record_assigned_to"), "case_record", ["assigned_to"], unique=False)
    op.create_index(op.f("ix_case_record_employer_ref"), "case_record", ["employer_ref"], unique=False)
    op.create_index(op.f("ix_case_record_finding_id"), "case_record", ["finding_id"], unique=False)
    op.create_index(op.f("ix_case_record_stage"), "case_record", ["stage"], unique=False)
    op.create_index(op.f("ix_case_record_tenant_id"), "case_record", ["tenant_id"], unique=False)
    op.create_index(
        "uq_active_case_per_finding_key",
        "case_record",
        ["tenant_id", "finding_key"],
        unique=True,
        postgresql_where=sa.text("stage NOT IN ('closed','rejected')"),
    )
    op.create_table(
        "finding_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["risk_finding.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_finding_event_finding_id"), "finding_event", ["finding_id"], unique=False)
    op.create_index(op.f("ix_finding_event_tenant_id"), "finding_event", ["tenant_id"], unique=False)
    op.create_table(
        "risk_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("source_record_ref", sa.String(length=200), nullable=False),
        sa.Column("field_name", sa.String(length=80), nullable=True),
        sa.Column("snapshot_value", sa.Text(), nullable=True),
        sa.Column("value_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["risk_finding.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_risk_evidence_finding_id"), "risk_evidence", ["finding_id"], unique=False)
    op.create_index(
        op.f("ix_risk_evidence_source_record_ref"), "risk_evidence", ["source_record_ref"], unique=False
    )
    op.create_index(op.f("ix_risk_evidence_tenant_id"), "risk_evidence", ["tenant_id"], unique=False)
    op.create_table(
        "case_action",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("template_code", sa.String(length=64), nullable=True),
        sa.Column("delivery_status", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("evidence_ref", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["case_record.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_case_action_case_id"), "case_action", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_action_tenant_id"), "case_action", ["tenant_id"], unique=False)
    op.create_table(
        "evidence_packet",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("exported_by", sa.String(length=100), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["case_record.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_packet_tenant_id"), "evidence_packet", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_packet_tenant_id"), table_name="evidence_packet")
    op.drop_table("evidence_packet")
    op.drop_index(op.f("ix_case_action_tenant_id"), table_name="case_action")
    op.drop_index(op.f("ix_case_action_case_id"), table_name="case_action")
    op.drop_table("case_action")
    op.drop_index(op.f("ix_risk_evidence_tenant_id"), table_name="risk_evidence")
    op.drop_index(op.f("ix_risk_evidence_source_record_ref"), table_name="risk_evidence")
    op.drop_index(op.f("ix_risk_evidence_finding_id"), table_name="risk_evidence")
    op.drop_table("risk_evidence")
    op.drop_index(op.f("ix_finding_event_tenant_id"), table_name="finding_event")
    op.drop_index(op.f("ix_finding_event_finding_id"), table_name="finding_event")
    op.drop_table("finding_event")
    op.drop_index(
        "uq_active_case_per_finding_key",
        table_name="case_record",
        postgresql_where=sa.text("stage NOT IN ('closed','rejected')"),
    )
    op.drop_index(op.f("ix_case_record_tenant_id"), table_name="case_record")
    op.drop_index(op.f("ix_case_record_stage"), table_name="case_record")
    op.drop_index(op.f("ix_case_record_finding_id"), table_name="case_record")
    op.drop_index(op.f("ix_case_record_employer_ref"), table_name="case_record")
    op.drop_index(op.f("ix_case_record_assigned_to"), table_name="case_record")
    op.drop_table("case_record")
    op.drop_index(op.f("ix_source_record_tenant_id"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_natural_id"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_employer_ref"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_batch_id"), table_name="source_record")
    op.drop_table("source_record")
    op.drop_index(op.f("ix_source_coverage_tenant_id"), table_name="source_coverage")
    op.drop_table("source_coverage")
    op.drop_index(op.f("ix_risk_signal_tenant_id"), table_name="risk_signal")
    op.drop_index(op.f("ix_risk_signal_run_id"), table_name="risk_signal")
    op.drop_table("risk_signal")
    op.drop_index("uq_finding_key_rule_version", table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_tenant_id"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_subject_id"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_status"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_signal_class"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_rule_code"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_period_code"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_lga_code"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_finding_key"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_employer_ref"), table_name="risk_finding")
    op.drop_index(op.f("ix_risk_finding_employer_id"), table_name="risk_finding")
    op.drop_table("risk_finding")
    op.drop_index(op.f("ix_period_schedule_tenant_id"), table_name="period_schedule")
    op.drop_table("period_schedule")
    op.drop_index(op.f("ix_taxpayer_identifier_token"), table_name="taxpayer_identifier")
    op.drop_index(op.f("ix_taxpayer_identifier_tenant_id"), table_name="taxpayer_identifier")
    op.drop_index(op.f("ix_taxpayer_identifier_taxpayer_id"), table_name="taxpayer_identifier")
    op.drop_table("taxpayer_identifier")
    op.drop_index(op.f("ix_programme_member_tenant_id"), table_name="programme_member")
    op.drop_index(op.f("ix_programme_member_programme_id"), table_name="programme_member")
    op.drop_table("programme_member")
    op.drop_index(op.f("ix_payment_allocation_tenant_id"), table_name="payment_allocation")
    op.drop_index(op.f("ix_payment_allocation_payment_id"), table_name="payment_allocation")
    op.drop_index(op.f("ix_payment_allocation_employer_id"), table_name="payment_allocation")
    op.drop_table("payment_allocation")
    op.drop_index(op.f("ix_legal_rule_version_tenant_id"), table_name="legal_rule_version")
    op.drop_index(op.f("ix_legal_rule_version_code"), table_name="legal_rule_version")
    op.drop_table("legal_rule_version")
    op.drop_index(
        "uq_batch_content", table_name="ingest_batch", postgresql_where=sa.text("qa_status <> 'rolled_back'")
    )
    op.drop_index(op.f("ix_ingest_batch_tenant_id"), table_name="ingest_batch")
    op.drop_index(op.f("ix_ingest_batch_feed_type"), table_name="ingest_batch")
    op.drop_table("ingest_batch")
    op.drop_index(op.f("ix_evaluation_run_tenant_id"), table_name="evaluation_run")
    op.drop_table("evaluation_run")
    op.drop_index(op.f("ix_taxpayer_tenant_id"), table_name="taxpayer")
    op.drop_index(op.f("ix_taxpayer_source_taxpayer_id"), table_name="taxpayer")
    op.drop_index(op.f("ix_taxpayer_is_current"), table_name="taxpayer")
    op.drop_index(op.f("ix_taxpayer_batch_id"), table_name="taxpayer")
    op.drop_table("taxpayer")
    op.drop_index(op.f("ix_tax_office_tenant_id"), table_name="tax_office")
    op.drop_table("tax_office")
    op.drop_index(op.f("ix_tax_obligation_tenant_id"), table_name="tax_obligation")
    op.drop_index(op.f("ix_tax_obligation_natural_key"), table_name="tax_obligation")
    op.drop_index(op.f("ix_tax_obligation_is_current"), table_name="tax_obligation")
    op.drop_index(op.f("ix_tax_obligation_employer_id"), table_name="tax_obligation")
    op.drop_index(op.f("ix_tax_obligation_batch_id"), table_name="tax_obligation")
    op.drop_table("tax_obligation")
    op.drop_index(op.f("ix_rule_version_tenant_id"), table_name="rule_version")
    op.drop_index(op.f("ix_rule_version_rule_code"), table_name="rule_version")
    op.drop_table("rule_version")
    op.drop_index(op.f("ix_rule_definition_tenant_id"), table_name="rule_definition")
    op.drop_table("rule_definition")
    op.drop_index(op.f("ix_return_filing_tenant_id"), table_name="return_filing")
    op.drop_index(op.f("ix_return_filing_period_code"), table_name="return_filing")
    op.drop_index(op.f("ix_return_filing_natural_key"), table_name="return_filing")
    op.drop_index(op.f("ix_return_filing_is_current"), table_name="return_filing")
    op.drop_index(op.f("ix_return_filing_employer_id"), table_name="return_filing")
    op.drop_index(op.f("ix_return_filing_batch_id"), table_name="return_filing")
    op.drop_table("return_filing")
    op.drop_index(op.f("ix_retention_policy_tenant_id"), table_name="retention_policy")
    op.drop_table("retention_policy")
    op.drop_index(op.f("ix_programme_tenant_id"), table_name="programme")
    op.drop_table("programme")
    op.drop_index(op.f("ix_payment_tenant_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_natural_key"), table_name="payment")
    op.drop_index(op.f("ix_payment_is_current"), table_name="payment")
    op.drop_index(op.f("ix_payment_employer_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_batch_id"), table_name="payment")
    op.drop_table("payment")
    op.drop_index(op.f("ix_lga_tenant_id"), table_name="lga")
    op.drop_table("lga")
    op.drop_index(op.f("ix_legal_instrument_tenant_id"), table_name="legal_instrument")
    op.drop_table("legal_instrument")
    op.drop_index(op.f("ix_input_snapshot_tenant_id"), table_name="input_snapshot")
    op.drop_table("input_snapshot")
    op.drop_index(op.f("ix_identity_match_tenant_id"), table_name="identity_match")
    op.drop_index(op.f("ix_identity_match_employer_id"), table_name="identity_match")
    op.drop_table("identity_match")
    op.drop_index(op.f("ix_idempotency_record_tenant_id"), table_name="idempotency_record")
    op.drop_table("idempotency_record")
    op.drop_index(op.f("ix_extension_tenant_id"), table_name="extension")
    op.drop_index(op.f("ix_extension_natural_key"), table_name="extension")
    op.drop_index(op.f("ix_extension_is_current"), table_name="extension")
    op.drop_index(op.f("ix_extension_employer_id"), table_name="extension")
    op.drop_index(op.f("ix_extension_batch_id"), table_name="extension")
    op.drop_table("extension")
    op.drop_index(op.f("ix_employer_tenant_id"), table_name="employer")
    op.drop_index(op.f("ix_employer_taxpayer_id"), table_name="employer")
    op.drop_index(op.f("ix_employer_source_employer_id"), table_name="employer")
    op.drop_index(op.f("ix_employer_is_current"), table_name="employer")
    op.drop_index(op.f("ix_employer_batch_id"), table_name="employer")
    op.drop_table("employer")
    op.drop_index(op.f("ix_data_source_tenant_id"), table_name="data_source")
    op.drop_table("data_source")
    op.drop_index(op.f("ix_audit_event_tenant_id"), table_name="audit_event")
    op.drop_index(op.f("ix_audit_event_subject_ref"), table_name="audit_event")
    op.drop_index(op.f("ix_audit_event_event_type"), table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_index(op.f("ix_assessment_tenant_id"), table_name="assessment")
    op.drop_index(op.f("ix_assessment_natural_key"), table_name="assessment")
    op.drop_index(op.f("ix_assessment_is_current"), table_name="assessment")
    op.drop_index(op.f("ix_assessment_employer_id"), table_name="assessment")
    op.drop_index(op.f("ix_assessment_batch_id"), table_name="assessment")
    op.drop_table("assessment")
    op.drop_index(op.f("ix_app_user_tenant_id"), table_name="app_user")
    op.drop_table("app_user")
    op.drop_table("tenant")
    op.execute("DROP SEQUENCE IF EXISTS ingest_batch_seq")
