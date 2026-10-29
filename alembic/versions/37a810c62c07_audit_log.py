"""audit log

The audit log of sensitive operations (S3.5, G-50): one row per operation of a
tenant, inserted in the operation's transaction, with the actor from the token,
the action, the resource, the relevant fields before and after, the source and
the request id. It gets row-level security like every business table, and the
entries can't be changed: the default privileges gave faclab_app and
faclab_worker UPDATE and DELETE on it, this revokes them (INSERT and SELECT
stay; no role has TRUNCATE).

Revision ID: 37a810c62c07
Revises: 47ed4694cbff
Create Date: 2026-10-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37a810c62c07"
down_revision: str | None = "47ed4694cbff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_tenant_id"), "audit_log", ["tenant_id"])
    op.create_index(op.f("ix_audit_log_occurred_at"), "audit_log", ["occurred_at"])
    op.create_index(op.f("ix_audit_log_actor_user_id"), "audit_log", ["actor_user_id"])
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_branch_id"), "audit_log", ["branch_id"])
    op.create_index(
        "ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"]
    )

    if _on_postgresql():
        op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON audit_log "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )
        op.execute("REVOKE UPDATE, DELETE ON audit_log FROM faclab_app, faclab_worker")


def downgrade() -> None:
    """Downgrade schema. The table's policy and grants go with it."""
    op.drop_index("ix_audit_log_resource", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_branch_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor_user_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_occurred_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_tenant_id"), table_name="audit_log")
    op.drop_table("audit_log")
