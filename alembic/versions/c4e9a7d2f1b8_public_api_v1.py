"""public api v1

The public API `/api/v1` (S6.3, G-72, G-73, G-42):

- `updated_at` in `products`, `customers` and `stocks`, and required in
  `sales`: integrations sync with `updatedSince`, ordered by `updated_at` and
  `id` (an index per table). Existing products and customers take their
  `created_at`, stock rows the moment of the migration and sales their
  `created_at` when they were never updated. Written with FORCE turned off on
  each table (faclab_owner, the owner, then skips the policy).
- `sales.channel` (`pos`, every existing sale, or `api`),
  `sales.external_reference` (the order id of the integrator's system) and
  `sales.integration_client_id` (composite key: the client is of the sale's
  tenant; `uq_integration_clients_tenant_id_id` is its target).
- `api_rate_limits`: the rate limit counters of the public API (D-6), a
  platform table without tenant nor row-level security; faclab_app and
  faclab_worker get their privileges by the default ones of `80bfd3a8c63b`.

The downgrade drops them: the channel of the API sales and the counters are
lost, and `sales.updated_at` is nullable again.

Revision ID: c4e9a7d2f1b8
Revises: b7d41c9e2a63
Create Date: 2026-11-17 18:00:00.000000

"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e9a7d2f1b8"
down_revision: str | None = "b7d41c9e2a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Table -> the value of updated_at in its existing rows
BACKFILL = {
    "products": "created_at",
    "customers": "created_at",
    "stocks": "CURRENT_TIMESTAMP",
}


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


@contextmanager
def _every_tenant(*tables: str) -> Iterator[None]:
    """Reads and writes the rows of every tenant of these tables"""
    if _on_postgresql():
        for table in tables:
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        yield
    finally:
        if _on_postgresql():
            for table in tables:
                op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """Upgrade schema."""
    for table in BACKFILL:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    with _every_tenant(*BACKFILL, "sales"):
        for table, value in BACKFILL.items():
            op.execute(f"UPDATE {table} SET updated_at = {value}")
        op.execute("UPDATE sales SET updated_at = created_at WHERE updated_at IS NULL")

    for table in (*BACKFILL, "sales"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "updated_at", existing_type=sa.DateTime(), nullable=False
            )
        op.create_index(
            f"ix_{table}_tenant_updated_at", table, ["tenant_id", "updated_at", "id"]
        )

    with op.batch_alter_table("integration_clients") as batch:
        batch.create_unique_constraint(
            "uq_integration_clients_tenant_id_id", ["tenant_id", "id"]
        )

    with op.batch_alter_table("sales") as batch:
        batch.add_column(
            sa.Column(
                "channel", sa.String(length=16), nullable=False, server_default="pos"
            )
        )
        batch.add_column(
            sa.Column("external_reference", sa.String(length=100), nullable=True)
        )
        batch.add_column(
            sa.Column("integration_client_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_sales_integration_client_tenant",
            "integration_clients",
            ["tenant_id", "integration_client_id"],
            ["tenant_id", "id"],
        )

    op.create_table(
        "api_rate_limits",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("tat", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("api_rate_limits")

    with op.batch_alter_table("sales") as batch:
        batch.drop_constraint("fk_sales_integration_client_tenant", type_="foreignkey")
        batch.drop_column("integration_client_id")
        batch.drop_column("external_reference")
        batch.drop_column("channel")

    with op.batch_alter_table("integration_clients") as batch:
        batch.drop_constraint("uq_integration_clients_tenant_id_id", type_="unique")

    op.drop_index("ix_sales_tenant_updated_at", table_name="sales")
    with op.batch_alter_table("sales") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=True)

    for table in BACKFILL:
        op.drop_index(f"ix_{table}_tenant_updated_at", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("updated_at")
