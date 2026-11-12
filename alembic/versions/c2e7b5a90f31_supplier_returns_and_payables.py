"""supplier returns and payables

Supplier returns and basic accounts payable (S5.7, F-11 and F-12):

- `purchase_order_items.quantity_returned` (0 by default): what each order line
  gave back to the supplier, in its presentation.
- `uq_purchase_orders_tenant_id_id`: the target of the composite key from the
  supplier returns.
- `supplier_returns` and `supplier_return_items`: goods of a received order
  going back to the supplier, numbered per tenant (`DP-2026-0001`,
  document_sequences with doc_type SUPPLIER_RETURN). Composite keys to the
  supplier, the order and each line's location; the line's order line, product
  and presentation are internal (the return's order).
- `payables`: one per purchase receipt with a total, with its balance and due
  date. A composite key to the supplier; the order and the receipt are internal
  (the receipt being created).
- `supplier_payments`: payments to suppliers, numbered per tenant
  (`PP-2026-0001`, doc_type SUPPLIER_PAYMENT). A composite key to the supplier.
- `payable_applications`: what a payment or a supplier return took off a
  payable, with a composite key to it and internal ones to the payment and the
  return.

Every new table has row-level security like every business table. Receipts
before S5.7 open no payable.

The downgrade drops the tables, the column and the constraint, and the counters
of the two new documents.

Revision ID: c2e7b5a90f31
Revises: 9d3f6a2c8e14
Create Date: 2026-11-12 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn, QuantityColumn

# revision identifiers, used by Alembic.
revision: str = "c2e7b5a90f31"
down_revision: str | None = "9d3f6a2c8e14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
INDEXES = {
    "supplier_returns": ("tenant_id", "supplier_id", "purchase_order_id", "status"),
    "supplier_return_items": (
        "tenant_id",
        "supplier_return_id",
        "purchase_order_item_id",
        "product_id",
        "presentation_id",
        "location_id",
    ),
    "supplier_payments": ("tenant_id", "supplier_id"),
    "payables": (
        "tenant_id",
        "supplier_id",
        "purchase_order_id",
        "purchase_receipt_id",
        "due_on",
        "status",
    ),
    "payable_applications": (
        "tenant_id",
        "payable_id",
        "supplier_payment_id",
        "supplier_return_id",
    ),
}


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _indexes_and_isolation(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def _drop(table: str) -> None:
    for column in reversed(INDEXES[table]):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("purchase_order_items") as batch:
        batch.add_column(
            sa.Column(
                "quantity_returned",
                QuantityColumn,
                nullable=False,
                server_default="0",
            )
        )
    with op.batch_alter_table("purchase_orders") as batch:
        batch.create_unique_constraint(
            "uq_purchase_orders_tenant_id_id", ["tenant_id", "id"]
        )

    op.create_table(
        "supplier_returns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("supplier_credit_note_number", sa.String(length=20), nullable=True),
        sa.Column("subtotal", MoneyColumn, nullable=False),
        sa.Column("tax", MoneyColumn, nullable=False),
        sa.Column("total", MoneyColumn, nullable=False),
        sa.Column("credited_amount", MoneyColumn, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "number", name="uq_supplier_returns_tenant_number"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_returns_supplier_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "purchase_order_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name="fk_supplier_returns_purchase_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "credited_amount >= 0 AND credited_amount <= total",
            name="ck_supplier_returns_credited_amount",
        ),
    )
    _indexes_and_isolation("supplier_returns")

    op.create_table(
        "supplier_return_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("supplier_return_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_item_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("presentation_id", sa.Integer(), nullable=True),
        sa.Column("quantity", QuantityColumn, nullable=False),
        sa.Column("unit_factor", QuantityColumn, nullable=False),
        sa.Column("base_quantity", QuantityColumn, nullable=False),
        sa.Column("unit_cost", MoneyColumn, nullable=False),
        sa.Column("tax_code", sa.String(length=16), nullable=False),
        sa.Column("tax_amount", MoneyColumn, nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=True),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["supplier_return_id"], ["supplier_returns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_item_id"],
            ["purchase_order_items.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["presentation_id"], ["product_presentations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_supplier_return_items_location_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_supplier_return_items_quantity"),
    )
    _indexes_and_isolation("supplier_return_items")

    op.create_table(
        "supplier_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("payment_method", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=False),
        sa.Column("paid_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "number", name="uq_supplier_payments_tenant_number"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_payments_supplier_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_supplier_payments_amount"),
    )
    _indexes_and_isolation("supplier_payments")

    op.create_table(
        "payables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_receipt_id", sa.Integer(), nullable=False),
        sa.Column("supplier_invoice_number", sa.String(length=20), nullable=True),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("balance", MoneyColumn, nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("term_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "purchase_receipt_id",
            name="uq_payables_tenant_purchase_receipt_id",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payables_tenant_id_id"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["purchase_receipt_id"], ["purchase_receipts.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_payables_supplier_tenant",
        ),
        sa.CheckConstraint(
            "amount > 0 AND balance >= 0 AND balance <= amount",
            name="ck_payables_balance",
        ),
    )
    _indexes_and_isolation("payables")

    op.create_table(
        "payable_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payable_id", sa.Integer(), nullable=False),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("supplier_payment_id", sa.Integer(), nullable=True),
        sa.Column("supplier_return_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["supplier_payment_id"], ["supplier_payments.id"]),
        sa.ForeignKeyConstraint(["supplier_return_id"], ["supplier_returns.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payable_id"],
            ["payables.tenant_id", "payables.id"],
            name="fk_payable_applications_payable_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payable_applications_amount"),
        sa.CheckConstraint(
            "(kind = 'PAYMENT' AND supplier_payment_id IS NOT NULL "
            "AND supplier_return_id IS NULL) OR "
            "(kind = 'RETURN' AND supplier_return_id IS NOT NULL "
            "AND supplier_payment_id IS NULL)",
            name="ck_payable_applications_source",
        ),
    )
    _indexes_and_isolation("payable_applications")


def downgrade() -> None:
    """Downgrade schema."""
    for table in (
        "payable_applications",
        "payables",
        "supplier_payments",
        "supplier_return_items",
        "supplier_returns",
    ):
        _drop(table)

    if _on_postgresql():
        op.execute("ALTER TABLE document_sequences NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DELETE FROM document_sequences "
        "WHERE doc_type IN ('SUPPLIER_RETURN', 'SUPPLIER_PAYMENT')"
    )
    if _on_postgresql():
        op.execute("ALTER TABLE document_sequences FORCE ROW LEVEL SECURITY")

    with op.batch_alter_table("purchase_orders") as batch:
        batch.drop_constraint("uq_purchase_orders_tenant_id_id", type_="unique")
    with op.batch_alter_table("purchase_order_items") as batch:
        batch.drop_column("quantity_returned")
