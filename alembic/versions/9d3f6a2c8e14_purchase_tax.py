"""purchase tax

Purchase VAT by rate (S5.7, G-37):

- `purchase_order_items.tax_code` (text, VAT_15 by default) and `tax_amount`
  (money, 0 by default): the product's VAT code when the line was added and the
  line's VAT at full precision. The cost never includes it.
- `purchase_receipts.supplier_invoice_number`, nullable, and `subtotal`, `tax`
  and `total`: what the receipt took at the order lines' costs, with their VAT.
  Its account payable (S5.7) is the total.

Existing lines take their product's current code (VAT_15 without one) and their
VAT (quantity ordered × cost × rate / 100). The tax and total of every order and
the totals of every receipt are recalculated as the code does: lines at full
precision, grouped by code and each group rounded to cents. The rates are fixed
here, as `TaxCode.rate` gives them today. The rows of every tenant are written
with FORCE turned off on each table (faclab_owner, the owner, then skips the
policy).

The downgrade drops the columns and puts the orders back to a tax of 0 (the
total is the subtotal again), as the code before S5.7 computed them.

Revision ID: 9d3f6a2c8e14
Revises: 720f0fa5fb74
Create Date: 2026-11-12 15:00:00.000000

"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn

# revision identifiers, used by Alembic.
revision: str = "9d3f6a2c8e14"
down_revision: str | None = "720f0fa5fb74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The VAT rate of a code, a percentage (TaxCode.rate)
RATE = (
    "(CASE {code} WHEN 'VAT_5' THEN 5 WHEN 'VAT_8_TOURISM' THEN 8 "
    "WHEN 'VAT_12' THEN 12 WHEN 'VAT_13' THEN 13 WHEN 'VAT_14' THEN 14 "
    "WHEN 'VAT_15' THEN 15 ELSE 0 END)"
)
# What each receipt line took, at its order line's cost
RECEIVED_LINES = (
    "FROM purchase_receipt_items ri "
    "JOIN purchase_order_items i ON i.id = ri.purchase_order_item_id "
    "WHERE ri.purchase_receipt_id = purchase_receipts.id"
)


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
    with op.batch_alter_table("purchase_order_items") as batch:
        batch.add_column(
            sa.Column(
                "tax_code", sa.String(16), nullable=False, server_default="VAT_15"
            )
        )
        batch.add_column(
            sa.Column("tax_amount", MoneyColumn, nullable=False, server_default="0")
        )
    with op.batch_alter_table("purchase_receipts") as batch:
        batch.add_column(
            sa.Column("supplier_invoice_number", sa.String(20), nullable=True)
        )
        for column in ("subtotal", "tax", "total"):
            batch.add_column(
                sa.Column(column, MoneyColumn, nullable=False, server_default="0")
            )

    with _every_tenant(
        "products",
        "purchase_orders",
        "purchase_order_items",
        "purchase_receipts",
        "purchase_receipt_items",
    ):
        op.execute(
            "UPDATE purchase_order_items SET tax_code = coalesce(("
            "SELECT p.tax_code FROM products p "
            "WHERE p.id = purchase_order_items.product_id "
            "AND p.tenant_id = purchase_order_items.tenant_id), 'VAT_15')"
        )
        op.execute(
            "UPDATE purchase_order_items SET tax_amount = "
            "unit_cost * quantity_ordered * " + RATE.format(code="tax_code") + " / 100"
        )
        op.execute(
            "UPDATE purchase_orders SET tax = coalesce(("
            "SELECT sum(g.tax) FROM ("
            "SELECT round(sum(i.tax_amount), 2) AS tax FROM purchase_order_items i "
            "WHERE i.purchase_order_id = purchase_orders.id GROUP BY i.tax_code"
            ") g), 0)"
        )
        op.execute("UPDATE purchase_orders SET total = subtotal + tax")
        op.execute(
            "UPDATE purchase_receipts SET subtotal = coalesce(("
            "SELECT round(sum(ri.quantity_received * i.unit_cost), 2) "
            + RECEIVED_LINES
            + "), 0)"
        )
        op.execute(
            "UPDATE purchase_receipts SET tax = coalesce(("
            "SELECT sum(g.tax) FROM ("
            "SELECT round(sum(ri.quantity_received * i.unit_cost * "
            + RATE.format(code="i.tax_code")
            + " / 100), 2) AS tax "
            + RECEIVED_LINES
            + " GROUP BY i.tax_code) g), 0)"
        )
        op.execute("UPDATE purchase_receipts SET total = subtotal + tax")


def downgrade() -> None:
    """Downgrade schema."""
    with _every_tenant("purchase_orders"):
        op.execute("UPDATE purchase_orders SET tax = 0, total = subtotal")
    with op.batch_alter_table("purchase_receipts") as batch:
        for column in ("total", "tax", "subtotal", "supplier_invoice_number"):
            batch.drop_column(column)
    with op.batch_alter_table("purchase_order_items") as batch:
        batch.drop_column("tax_amount")
        batch.drop_column("tax_code")
