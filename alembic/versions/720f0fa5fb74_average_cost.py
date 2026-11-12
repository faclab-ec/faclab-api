"""average cost

Weighted average cost and a valued kardex (S5.6, F-09):

- `movements.unit_cost`: what each movement moved at, per base unit. An IN
  brings its cost (the purchase line, the source of a transfer, the sale it
  reverses); an OUT takes the average of its location.
- `stocks.average_cost`: the weighted average cost of the product in that
  location, recalculated by every IN under the lock of the stock row.
- `adjustment_items.unit_cost`, nullable: the cost of what a count adds over the
  system (initial balances); without it the units enter at the average.

Existing movements and stock rows take the purchase price of their product (0
without one), so the kardex of the data already there adds up to its valuation.
They are written with FORCE turned off on each table (faclab_owner, the owner,
then skips the policy). Both columns are non-negative.

The downgrade drops the three columns: the costs are lost.

Revision ID: 720f0fa5fb74
Revises: b5e2c8d41f07
Create Date: 2026-11-12 10:00:00.000000

"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn

# revision identifiers, used by Alembic.
revision: str = "720f0fa5fb74"
down_revision: str | None = "b5e2c8d41f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURCHASE_PRICE = (
    "coalesce((SELECT p.purchase_price FROM products p "
    "WHERE p.id = {table}.product_id AND p.tenant_id = {table}.tenant_id), 0)"
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
    with op.batch_alter_table("movements") as batch:
        batch.add_column(sa.Column("unit_cost", MoneyColumn, nullable=True))
    with op.batch_alter_table("stocks") as batch:
        batch.add_column(sa.Column("average_cost", MoneyColumn, nullable=True))
    with op.batch_alter_table("adjustment_items") as batch:
        batch.add_column(sa.Column("unit_cost", MoneyColumn, nullable=True))

    with _every_tenant("movements", "stocks", "products"):
        op.execute(
            "UPDATE movements SET unit_cost = "
            + PURCHASE_PRICE.format(table="movements")
        )
        op.execute(
            "UPDATE stocks SET average_cost = " + PURCHASE_PRICE.format(table="stocks")
        )

    with op.batch_alter_table("movements") as batch:
        batch.alter_column("unit_cost", existing_type=MoneyColumn, nullable=False)
        batch.create_check_constraint(
            "ck_movements_unit_cost_non_negative", "unit_cost >= 0"
        )
    with op.batch_alter_table("stocks") as batch:
        batch.alter_column("average_cost", existing_type=MoneyColumn, nullable=False)
        batch.create_check_constraint(
            "ck_stocks_average_cost_non_negative", "average_cost >= 0"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("adjustment_items") as batch:
        batch.drop_column("unit_cost")
    with op.batch_alter_table("stocks") as batch:
        batch.drop_constraint("ck_stocks_average_cost_non_negative", type_="check")
        batch.drop_column("average_cost")
    with op.batch_alter_table("movements") as batch:
        batch.drop_constraint("ck_movements_unit_cost_non_negative", type_="check")
        batch.drop_column("unit_cost")
