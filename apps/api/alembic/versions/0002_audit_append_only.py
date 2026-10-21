"""Make audit_events append-only at the database layer (PostgreSQL).

Defence in depth alongside the application hash chain: UPDATE and DELETE on audit_events raise,
even for the application role. Retention purges must run as a separate, audited DBA procedure.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION taxcris_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_events_immutable
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION taxcris_audit_immutable();
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events; DROP FUNCTION IF EXISTS taxcris_audit_immutable();")
