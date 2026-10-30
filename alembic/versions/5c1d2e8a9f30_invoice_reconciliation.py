"""invoice reconciliation

Reconciliation between sales and faclab-invoicing (S4.3, G-21):

- `sales.invoice_requested_at`: when the sale was last sent to invoicing (set on
  confirm and on every resend). The reconciliation measures from it how long a
  PENDING invoice has waited. Pending sales take their `updated_at` (the sale
  became PENDING in its last update), with FORCE off while the backfill runs.
- `ix_sales_confirmed_tenant`: the confirmed sales of a tenant, the ones the
  reconciliation looks at.
- `invoice_discrepancies`: a sale that doesn't square with invoicing, at most one
  unresolved per sale and kind. Row-level security like every business table.

Revision ID: 5c1d2e8a9f30
Revises: 37a810c62c07
Create Date: 2026-10-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5c1d2e8a9f30"
down_revision: str | None = "37a810c62c07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sales", sa.Column("invoice_requested_at", sa.DateTime(), nullable=True)
    )
    if _on_postgresql():
        op.execute("ALTER TABLE sales NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE sales SET invoice_requested_at = COALESCE(updated_at, created_at) "
        "WHERE invoice_status = 'PENDING'"
    )
    if _on_postgresql():
        op.execute("ALTER TABLE sales FORCE ROW LEVEL SECURITY")
    op.create_index(
        "ix_sales_confirmed_tenant",
        "sales",
        ["tenant_id"],
        postgresql_where=sa.text("status = 'CONFIRMED'"),
        sqlite_where=sa.text("status = 'CONFIRMED'"),
    )

    op.create_table(
        "invoice_discrepancies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("invoice_id", sa.String(length=64), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(length=64), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invoice_discrepancies_tenant_id"),
        "invoice_discrepancies",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_invoice_discrepancies_sale_id"), "invoice_discrepancies", ["sale_id"]
    )
    op.create_index(
        op.f("ix_invoice_discrepancies_status"), "invoice_discrepancies", ["status"]
    )
    op.create_index(
        "uq_invoice_discrepancies_tenant_sale_kind_unresolved",
        "invoice_discrepancies",
        ["tenant_id", "sale_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
        sqlite_where=sa.text("status <> 'resolved'"),
    )

    if _on_postgresql():
        op.execute("ALTER TABLE invoice_discrepancies ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE invoice_discrepancies FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON invoice_discrepancies "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema. The table's policy and grants go with it."""
    op.drop_index(
        "uq_invoice_discrepancies_tenant_sale_kind_unresolved",
        table_name="invoice_discrepancies",
    )
    op.drop_index(
        op.f("ix_invoice_discrepancies_status"), table_name="invoice_discrepancies"
    )
    op.drop_index(
        op.f("ix_invoice_discrepancies_sale_id"), table_name="invoice_discrepancies"
    )
    op.drop_index(
        op.f("ix_invoice_discrepancies_tenant_id"), table_name="invoice_discrepancies"
    )
    op.drop_table("invoice_discrepancies")
    op.drop_index("ix_sales_confirmed_tenant", table_name="sales")
    with op.batch_alter_table("sales") as batch:
        batch.drop_column("invoice_requested_at")
