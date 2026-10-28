"""Row-level security, append-only audit, immutable approved versions.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen list of tenant-scoped tables at this revision. A later migration that adds a
# tenant table must enable RLS for it; tests/integration/test_tenant_isolation.py
# fails if any tenant_id table lacks a policy.
TENANT_TABLES = [
    "app_user",
    "assessment",
    "audit_event",
    "data_source",
    "employer",
    "extension",
    "idempotency_record",
    "identity_match",
    "input_snapshot",
    "legal_instrument",
    "lga",
    "payment",
    "programme",
    "retention_policy",
    "return_filing",
    "rule_definition",
    "rule_version",
    "tax_obligation",
    "tax_office",
    "taxpayer",
    "evaluation_run",
    "ingest_batch",
    "legal_rule_version",
    "payment_allocation",
    "programme_member",
    "taxpayer_identifier",
    "period_schedule",
    "risk_finding",
    "risk_signal",
    "source_coverage",
    "source_record",
    "case_record",
    "finding_event",
    "risk_evidence",
    "case_action",
    "evidence_packet",
]
APPEND_ONLY = ["audit_event", "finding_event", "case_action", "risk_evidence", "evidence_packet"]
TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    # Tenant isolation: every tenant-scoped table, enforced for every role except superusers.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})"
        )
    # tenant: RLS for the application role; not FORCEd, so the owner-defined resolver below can look up a
    # tenant id by code (it returns only the id, never another tenant's row).
    op.execute("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_self ON tenant USING (id = {TENANT_EXPR}) WITH CHECK (id = {TENANT_EXPR})"
    )

    # Resolve a tenant code to its id without exposing other tenants' rows.
    op.execute("""
        CREATE FUNCTION app_resolve_tenant(p_code text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT id FROM tenant WHERE code = p_code $$
    """)

    op.execute("""
        CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only: % refused', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$
    """)
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
        )

    op.execute("""
        CREATE FUNCTION protect_approved_rule_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status NOT IN ('draft', 'validated', 'rejected') THEN
              RAISE EXCEPTION 'approved rule versions cannot be deleted' USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status IN ('approved', 'active', 'retired')
             AND (NEW.expression_json IS DISTINCT FROM OLD.expression_json
                  OR NEW.version IS DISTINCT FROM OLD.version
                  OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                  OR NEW.rule_code IS DISTINCT FROM OLD.rule_code) THEN
            RAISE EXCEPTION 'rule version % % is approved and immutable; create a new version', OLD.rule_code,
              OLD.version USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER rule_version_immutable BEFORE UPDATE OR DELETE ON rule_version "
        "FOR EACH ROW EXECUTE FUNCTION protect_approved_rule_version()"
    )
    op.execute("""
        CREATE FUNCTION protect_approved_legal_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'legal versions cannot be deleted once submitted'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN OLD;
          END IF;
          IF OLD.status IN ('approved', 'retired')
             AND (NEW.parameters IS DISTINCT FROM OLD.parameters
                  OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
                  OR NEW.effective_to IS DISTINCT FROM OLD.effective_to
                  OR NEW.content_hash IS DISTINCT FROM OLD.content_hash) THEN
            RAISE EXCEPTION 'approved legal version % % is immutable', OLD.code, OLD.version
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER legal_version_immutable BEFORE UPDATE OR DELETE ON legal_rule_version "
        "FOR EACH ROW EXECUTE FUNCTION protect_approved_legal_version()"
    )

    op.execute("GRANT USAGE ON SCHEMA public TO ngsirs_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ngsirs_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ngsirs_app")
    op.execute("GRANT EXECUTE ON FUNCTION app_resolve_tenant(text) TO ngsirs_app")
    for table in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM ngsirs_app")


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP TRIGGER IF EXISTS rule_version_immutable ON rule_version")
    op.execute("DROP TRIGGER IF EXISTS legal_version_immutable ON legal_rule_version")
    op.execute("DROP FUNCTION IF EXISTS protect_approved_rule_version()")
    op.execute("DROP FUNCTION IF EXISTS protect_approved_legal_version()")
    op.execute("DROP FUNCTION IF EXISTS forbid_mutation()")
    op.execute("DROP FUNCTION IF EXISTS app_resolve_tenant(text)")
    for table in [*TENANT_TABLES, "tenant"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_self ON tenant")
