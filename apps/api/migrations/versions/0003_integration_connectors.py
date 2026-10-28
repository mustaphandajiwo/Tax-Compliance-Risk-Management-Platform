"""integration connectors

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 08:35:41.366696
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("secret_env", sa.String(length=100), nullable=True),
        sa.Column("webhook_secret_env", sa.String(length=100), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schedule_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_source.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code"),
    )
    op.create_index(op.f("ix_connector_tenant_id"), "connector", ["tenant_id"], unique=False)
    op.create_table(
        "connector_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "connector_id", "event_id"),
    )
    op.create_index(op.f("ix_connector_event_tenant_id"), "connector_event", ["tenant_id"], unique=False)
    op.create_table(
        "connector_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("feed_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cursor_from", sa.String(length=100), nullable=True),
        sa.Column("cursor_to", sa.String(length=100), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_filtered", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connector.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_connector_run_connector_id"), "connector_run", ["connector_id"], unique=False)
    op.create_index(op.f("ix_connector_run_tenant_id"), "connector_run", ["tenant_id"], unique=False)

    tenant_expr = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in ("connector", "connector_run", "connector_event"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {tenant_expr}) WITH CHECK (tenant_id = {tenant_expr})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO ngsirs_app")
    op.execute("REVOKE UPDATE, DELETE ON connector_event FROM ngsirs_app")


def downgrade() -> None:
    op.drop_index(op.f("ix_connector_run_tenant_id"), table_name="connector_run")
    op.drop_index(op.f("ix_connector_run_connector_id"), table_name="connector_run")
    op.drop_table("connector_run")
    op.drop_index(op.f("ix_connector_event_tenant_id"), table_name="connector_event")
    op.drop_table("connector_event")
    op.drop_index(op.f("ix_connector_tenant_id"), table_name="connector")
    op.drop_table("connector")
