"""Row-level security on all tenant-scoped tables (Postgres only).

Each policy ties rows to the `app.current_tenant` session setting, which
TenantMiddleware sets per request (and RESETs afterwards so pooled
connections can't leak identity).

Notes:
  * FORCE ROW LEVEL SECURITY: policies apply even to the table owner (the
    role Django connects as). Without FORCE, RLS would silently not apply.
  * `current_setting('app.current_tenant', true)` returns NULL when unset;
    NULL::uuid comparisons are never true, so the policy FAILS CLOSED.
  * Identity tables (tenants_tenant, accounts_user) are intentionally NOT
    covered: they must be readable before a tenant is resolved (login).
    The middleware's user.tenant_id == token tenant check covers them.

On SQLite this migration is a no-op (RunPython checks the vendor).
"""
from django.db import migrations

TENANT_TABLES = [
    "kb_knowledgebase",
    "kb_document",
    "kb_chunk",
    "chat_conversation",
    "chat_message",
]

POLICY_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = '{table}' AND policyname = 'tenant_isolation'
    ) THEN
        EXECUTE 'CREATE POLICY tenant_isolation ON {table}
                 USING (tenant_id = current_setting(''app.current_tenant'', true)::uuid)
                 WITH CHECK (tenant_id = current_setting(''app.current_tenant'', true)::uuid)';
    END IF;
END $$;
"""


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in TENANT_TABLES:
            cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            cur.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            cur.execute(POLICY_SQL.format(table=table))


def remove_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in TENANT_TABLES:
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            cur.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            cur.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0001_initial"),
        ("accounts", "0001_initial"),
        ("kb", "0001_initial"),
        ("chat", "0001_initial"),
    ]
    operations = [migrations.RunPython(apply_rls, remove_rls)]
