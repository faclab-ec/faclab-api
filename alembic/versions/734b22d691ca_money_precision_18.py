"""money precision 18

Money columns go from numeric(12, 6) to numeric(18, 6) (S3.3): up to
999,999,999,999.999999 instead of 999,999.999999, which a purchase order or a
report total can exceed. Same scale, so PostgreSQL changes the type without
rewriting the tables.

The downgrade goes back to numeric(12, 6) and fails, naming the column, if a
row holds an amount that doesn't fit.

Revision ID: 734b22d691ca
Revises: 6b206e24e504
Create Date: 2026-10-27 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "734b22d691ca"
down_revision: str | None = "6b206e24e504"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = sa.Numeric(precision=12, scale=6)
AFTER = sa.Numeric(precision=18, scale=6)

# Every money column at this revision
MONEY_COLUMNS = {
    "customers": ("credit_limit",),
    "payments": ("amount", "amount_tendered", "change"),
    "pos_cash_movements": ("amount",),
    "pos_refund_items": ("unit_price", "tax_amount"),
    "pos_refund_payments": ("amount",),
    "pos_refunds": ("subtotal", "tax", "total"),
    "pos_shifts": (
        "opening_balance",
        "closing_balance",
        "expected_balance",
        "discrepancy",
    ),
    "products": ("purchase_price", "sale_price"),
    "purchase_order_items": ("unit_cost",),
    "purchase_orders": ("subtotal", "tax", "total"),
    "sale_items": ("unit_price", "tax_amount", "price_override"),
    "sales": ("subtotal", "tax", "discount", "discount_value", "total"),
    "supplier_products": ("purchase_price",),
}


def _retype(existing: sa.Numeric, new: sa.Numeric) -> None:
    for table, columns in MONEY_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(column, existing_type=existing, type_=new)


def upgrade() -> None:
    _retype(BEFORE, AFTER)


def downgrade() -> None:
    _retype(AFTER, BEFORE)
