"""idempotency keys

The `Idempotency-Key` of the POS routes that create documents or move money
(S3.1): one row per key of a tenant, reserved and completed with its response
in the transaction of the request. It gets row-level security like every
business table; the purge (`python -m src.shared.infra.idempotency.purge`) runs
as faclab_worker and deletes the old rows of every tenant.

Revision ID: 4e07e6cd9e67
Revises: 654849d8d497
Create Date: 2026-10-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4e07e6cd9e67"
down_revision: str | None = "654849d8d497"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),
    )
    op.create_index(
        op.f("ix_idempotency_keys_tenant_id"), "idempotency_keys", ["tenant_id"]
    )
    op.create_index(
        op.f("ix_idempotency_keys_created_at"), "idempotency_keys", ["created_at"]
    )

    if _on_postgresql():
        op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON idempotency_keys "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema. The table's policy goes with it."""
    op.drop_index(op.f("ix_idempotency_keys_created_at"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_tenant_id"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
