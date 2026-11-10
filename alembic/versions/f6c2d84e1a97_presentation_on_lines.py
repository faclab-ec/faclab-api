"""presentation on lines

Sale, refund and purchase lines are in a presentation of their product (S5.2,
F-02): their quantity and price are of that presentation (2 boxes at $4.50) and
the stock moves quantity × the presentation's factor, copied into the line.

- `sale_items`, `pos_refund_items`: `presentation_id`, `unit_factor` and
  `base_quantity` (what moved the stock, for the reports).
- `purchase_order_items`: `presentation_id` and `unit_factor` (ordered, received
  and pending are in the presentation).
- `purchase_receipt_items`: `unit_factor` and `base_quantity` (what went in).

Every existing line was in base units: factor 1, its quantity as base quantity
and the base presentation of its product. The rows of every tenant are filled
with FORCE turned off on each table while it is written (faclab_owner, the
owner, then skips the policy).

The downgrade fails, naming the table, while a line is in a presentation other
than the base unit: going back would read its boxes as units.

Revision ID: f6c2d84e1a97
Revises: e3b7a91c5d20
Create Date: 2026-11-10 13:00:00.000000

"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import QuantityColumn

# revision identifiers, used by Alembic.
revision: str = "f6c2d84e1a97"
down_revision: str | None = "e3b7a91c5d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Line table -> its quantity column, for the ones that store base_quantity
BASE_QUANTITY_TABLES = {
    "sale_items": "quantity",
    "pos_refund_items": "quantity",
    "purchase_receipt_items": "quantity_received",
}
# Line tables that point at their presentation
PRESENTATION_TABLES = ("sale_items", "pos_refund_items", "purchase_order_items")
FACTOR_TABLES = (*PRESENTATION_TABLES, "purchase_receipt_items")


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
    for table in FACTOR_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "unit_factor", QuantityColumn, nullable=False, server_default="1"
                )
            )
    for table in PRESENTATION_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("presentation_id", sa.Integer(), nullable=True))
        op.create_index(op.f(f"ix_{table}_presentation_id"), table, ["presentation_id"])
    for table in BASE_QUANTITY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("base_quantity", QuantityColumn, nullable=True))

    # Every existing line was in base units, of its product's base presentation
    for table, quantity in BASE_QUANTITY_TABLES.items():
        with _every_tenant(table):
            op.execute(f"UPDATE {table} SET base_quantity = {quantity}")
    for table in PRESENTATION_TABLES:
        with _every_tenant(table, "product_presentations"):
            op.execute(
                f"UPDATE {table} SET presentation_id = ("
                "SELECT pp.id FROM product_presentations pp "
                f"WHERE pp.product_id = {table}.product_id "
                f"AND pp.tenant_id = {table}.tenant_id AND pp.is_base)"
            )

    for table in BASE_QUANTITY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "base_quantity", existing_type=QuantityColumn, nullable=False
            )
    for table in ("sale_items", "purchase_order_items"):
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                f"fk_{table}_presentation_tenant",
                "product_presentations",
                ["tenant_id", "presentation_id"],
                ["tenant_id", "id"],
            )
    # Copied from the sale item, like its product
    with op.batch_alter_table("pos_refund_items") as batch:
        batch.create_foreign_key(
            "fk_pos_refund_items_presentation",
            "product_presentations",
            ["presentation_id"],
            ["id"],
        )


def _ensure_base_units(table: str) -> None:
    """Fails naming the table while a line is in another presentation"""
    with _every_tenant(table):
        other = (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} WHERE unit_factor <> 1 LIMIT 1"))
            .first()
        )
    if other is not None:
        raise RuntimeError(
            f"{table} holds lines in a presentation other than the base unit: "
            "going back would read their quantity as base units"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in FACTOR_TABLES:
        _ensure_base_units(table)

    with op.batch_alter_table("pos_refund_items") as batch:
        batch.drop_constraint("fk_pos_refund_items_presentation", type_="foreignkey")
    for table in ("sale_items", "purchase_order_items"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_presentation_tenant", type_="foreignkey")
    for table in BASE_QUANTITY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("base_quantity")
    for table in PRESENTATION_TABLES:
        op.drop_index(op.f(f"ix_{table}_presentation_id"), table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("presentation_id")
    for table in FACTOR_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("unit_factor")
