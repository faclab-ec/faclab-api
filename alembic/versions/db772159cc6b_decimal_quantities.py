"""decimal quantities

Quantities go from integer to numeric(18, 6) (S5.1, F-01): stock, movements,
adjustments, transfers, lots, sale, refund and purchase lines, and the stock
thresholds of products and suppliers. Six decimals is what the SRI's XML 1.1.0
takes in `cantidad`. Every integer keeps its value; PostgreSQL rewrites the
tables (there is no productive data yet).

`units_of_measure.decimals` says how many decimals a quantity in that unit takes,
from 0 to 6. Every existing unit gets 0, so nothing changes until a company gives
its meters or kilograms some decimals.

The downgrade goes back to integer and fails, naming the column, if a row holds
a fraction. The check turns FORCE off on each table while it reads it
(faclab_owner, the owner, then skips the policy and sees every tenant).

Revision ID: db772159cc6b
Revises: d8e4f2a1b6c3
Create Date: 2026-11-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db772159cc6b"
down_revision: str | None = "d8e4f2a1b6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTEGER = sa.Integer()
QUANTITY = sa.Numeric(precision=18, scale=6)

# Every quantity column at this revision
QUANTITY_COLUMNS = {
    "adjustment_items": ("expected_quantity", "actual_quantity"),
    "lots": ("initial_quantity", "current_quantity"),
    "movement_lot_items": ("quantity",),
    "movements": ("quantity",),
    "pos_refund_items": ("quantity",),
    "products": ("min_stock", "max_stock", "reorder_point"),
    "purchase_order_items": ("quantity_ordered", "quantity_received"),
    "purchase_receipt_items": ("quantity_received",),
    "sale_items": ("quantity",),
    "stock_transfer_items": ("quantity",),
    "stocks": ("quantity", "reserved_quantity"),
    "supplier_products": ("min_order_quantity",),
}


def _postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _ensure_whole_numbers(table: str, columns: Sequence[str]) -> None:
    """Fails naming the first column that holds a fraction, in any tenant"""
    bind = op.get_bind()
    if _postgresql():
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        for column in columns:
            fraction = bind.execute(
                sa.text(
                    f"SELECT 1 FROM {table} WHERE {column} <> trunc({column}) LIMIT 1"
                )
            ).first()
            if fraction is not None:
                raise RuntimeError(
                    f"{table}.{column} holds a fractional quantity: round it by "
                    "hand before going back to integer quantities"
                )
    finally:
        if _postgresql():
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """Upgrade schema."""
    for table, columns in QUANTITY_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(
                    column,
                    existing_type=INTEGER,
                    type_=QUANTITY,
                    postgresql_using=f"{column}::numeric(18, 6)",
                )

    with op.batch_alter_table("units_of_measure") as batch:
        batch.add_column(
            sa.Column("decimals", sa.SmallInteger(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            "ck_units_of_measure_decimals", "decimals >= 0 AND decimals <= 6"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("units_of_measure") as batch:
        batch.drop_constraint("ck_units_of_measure_decimals", type_="check")
        batch.drop_column("decimals")

    for table, columns in QUANTITY_COLUMNS.items():
        _ensure_whole_numbers(table, columns)
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(
                    column,
                    existing_type=QUANTITY,
                    type_=INTEGER,
                    postgresql_using=f"{column}::integer",
                )
