"""tenant offboarding

Termination of a company's contract (S8.7):

- `tenants` gets the dates of the procedure: when it started, when the grace
  period ends, until when tax law makes us keep what was issued, and when the
  personal data was anonymized. The new status `offboarded` is text: no change.
- `faclab_anonymize_append_only` and `faclab_purge_append_only`: the one way the
  worker can touch `audit_log`, `pos_shift_closings` and its lines, which the
  roles of the app and the worker may not UPDATE or DELETE (S3.5, S5.9). They
  belong to faclab_owner (SECURITY DEFINER), work on the one tenant they are
  given, and only faclab_worker may run them.

The downgrade drops the columns and the functions; an offboarded tenant stays
with its data anonymized.

Revision ID: e6b2a9c4d715
Revises: d4a7c1e8b903
Create Date: 2026-11-25 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b2a9c4d715"
down_revision: str | None = "d4a7c1e8b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "offboarding_started_at",
    "grace_ends_at",
    "retention_ends_at",
    "anonymized_at",
)

ANONYMIZE = """
CREATE OR REPLACE FUNCTION faclab_anonymize_append_only(p_tenant uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    audited integer;
    closed integer;
BEGIN
    -- Row-level security is forced on the owner too: act as the tenant
    PERFORM set_config('app.tenant_id', p_tenant::text, true);
    -- The platform's own entries (the operator's) are not the tenant's data
    UPDATE audit_log
       SET actor_name = 'Usuario anonimizado',
           before = CASE WHEN json_typeof(before) = 'object'
                    THEN (before::jsonb - ARRAY['full_name', 'username', 'email',
                         'name', 'phone', 'address', 'tax_id'])::json ELSE before END,
           after = CASE WHEN json_typeof(after) = 'object'
                   THEN (after::jsonb - ARRAY['full_name', 'username', 'email',
                        'name', 'phone', 'address', 'tax_id'])::json ELSE after END
     WHERE tenant_id = p_tenant
       AND action NOT LIKE 'tenant.%'
       AND action <> 'subscription.changed';
    GET DIAGNOSTICS audited = ROW_COUNT;
    UPDATE pos_shift_closings
       SET cashier_name = 'Cajero anonimizado',
           closed_by = CASE WHEN closed_by IS NULL THEN NULL
                       ELSE 'Usuario anonimizado' END,
           notes = NULL
     WHERE tenant_id = p_tenant;
    GET DIAGNOSTICS closed = ROW_COUNT;
    RETURN audited + closed;
END
$$
"""

PURGE = """
CREATE OR REPLACE FUNCTION faclab_purge_append_only(p_tenant uuid)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    lines integer;
    closed integer;
    audited integer;
BEGIN
    PERFORM set_config('app.tenant_id', p_tenant::text, true);
    DELETE FROM pos_shift_closing_lines WHERE tenant_id = p_tenant;
    GET DIAGNOSTICS lines = ROW_COUNT;
    DELETE FROM pos_shift_closings WHERE tenant_id = p_tenant;
    GET DIAGNOSTICS closed = ROW_COUNT;
    DELETE FROM audit_log WHERE tenant_id = p_tenant;
    GET DIAGNOSTICS audited = ROW_COUNT;
    RETURN lines + closed + audited;
END
$$
"""

FUNCTIONS = ("faclab_anonymize_append_only", "faclab_purge_append_only")


def upgrade() -> None:
    """Upgrade schema."""
    for column in COLUMNS:
        op.add_column("tenants", sa.Column(column, sa.DateTime(), nullable=True))
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(ANONYMIZE)
    op.execute(PURGE)
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function}(uuid) FROM PUBLIC")
        op.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
            f"'faclab_worker') THEN GRANT EXECUTE ON FUNCTION {function}(uuid) "
            "TO faclab_worker; END IF; END $$"
        )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == "postgresql":
        for function in FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {function}(uuid)")
    for column in reversed(COLUMNS):
        op.drop_column("tenants", column)
