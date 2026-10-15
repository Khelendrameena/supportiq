"""Fix the tenant_isolation RLS policy to fail closed on empty settings.

0002's policy compared `tenant_id = current_setting('app.current_tenant',
true)::uuid`. That is only fail-closed when the setting is truly unset
(NULL). In practice the middleware RESETs the setting after each request,
and Postgres RESET of a custom GUC leaves an *empty string* -- and
`''::uuid` raises `invalid input syntax` instead of comparing false.

This migration drops and recreates the policy with a NULLIF guard, so both
the never-set (NULL) and reset ('') states fail closed instead of erroring.
"""
from django.db import migrations

TENANT_TABLES = [
    "kb_knowledgebase",
    "kb_document",
    "kb_chunk",
    "chat_conversation",
    "chat_message",
]

# Same NULLIF-guarded expression as 0002's POLICY_SQL; duplicated here so
# this migration is self-contained for databases that already ran 0002.
POLICY_DDL = (
    "CREATE POLICY tenant_isolation ON {table} "
    "USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
    "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
)


def fix_policies(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        for table in TENANT_TABLES:
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            cur.execute(POLICY_DDL.format(table=table))


def noop(apps, schema_editor):
    # Irreversible on purpose: reverting would restore the erroring policy.
    pass


class Migration(migrations.Migration):
    dependencies = [("tenants", "0002_rls_policies")]

    operations = [migrations.RunPython(fix_policies, noop)]
