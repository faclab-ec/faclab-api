"""product presentations

Presentations of a product (S5.2, F-02, F-03): its base unit and others such as a
box of 100 or a roll of 50 m, each with a decimal factor to the base unit, its
own barcode and its own price and cost.

- The base unit becomes required: a product without one gets the tenant's `und`
  unit, created as "Unidad" (0 decimals) when the tenant has none.
- `product_presentations`, with row-level security like every business table.
  Every product gets its base presentation: factor 1, named after its unit, with
  the product's barcode. Barcodes live there since, unique per tenant among every
  presentation; `products.barcode` and `uq_products_tenant_barcode` go away.

The data of every tenant moves with FORCE turned off on each table while it is
written (faclab_owner, the owner, then skips the policy); the new table gets its
policy after it is filled.

The downgrade puts each product's barcode back from its base presentation and
drops the table: the other presentations are lost. Products keep the unit they
were given.

Revision ID: e3b7a91c5d20
Revises: db772159cc6b
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn, QuantityColumn

# revision identifiers, used by Alembic.
revision: str = "e3b7a91c5d20"
down_revision: str | None = "db772159cc6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


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
    # 1. Every product has its base unit
    with _every_tenant("products", "units_of_measure"):
        op.execute(
            "INSERT INTO units_of_measure "
            "(tenant_id, name, symbol, description, is_active, decimals) "
            "SELECT DISTINCT p.tenant_id, 'Unidad', 'und', NULL, true, 0 "
            "FROM products p WHERE p.unit_of_measure_id IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM units_of_measure u "
            "WHERE u.tenant_id = p.tenant_id AND u.symbol = 'und')"
        )
        op.execute(
            "UPDATE products SET unit_of_measure_id = ("
            "SELECT u.id FROM units_of_measure u "
            "WHERE u.tenant_id = products.tenant_id AND u.symbol = 'und') "
            "WHERE unit_of_measure_id IS NULL"
        )
    with op.batch_alter_table("products") as batch:
        batch.alter_column(
            "unit_of_measure_id", existing_type=sa.Integer(), nullable=False
        )

    # 2. Presentations, each product with its base one
    op.create_table(
        "product_presentations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("factor", QuantityColumn, nullable=False),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("sale_price", MoneyColumn, nullable=True),
        sa.Column("purchase_price", MoneyColumn, nullable=True),
        sa.Column("is_base", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_presentations_product_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "barcode", name="uq_product_presentations_tenant_barcode"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "name",
            name="uq_product_presentations_tenant_product_name",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_product_presentations_tenant_id_id"
        ),
        sa.CheckConstraint(
            "factor > 0", name="ck_product_presentations_factor_positive"
        ),
        sa.CheckConstraint(
            "NOT is_base OR (factor = 1 AND sale_price IS NULL "
            "AND purchase_price IS NULL AND is_active)",
            name="ck_product_presentations_base",
        ),
    )
    op.create_index(
        op.f("ix_product_presentations_tenant_id"),
        "product_presentations",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_product_presentations_product_id"),
        "product_presentations",
        ["product_id"],
    )
    op.create_index(
        "uq_product_presentations_tenant_product_base",
        "product_presentations",
        ["tenant_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_base"),
        sqlite_where=sa.text("is_base"),
    )

    with _every_tenant("products", "units_of_measure"):
        op.execute(
            "INSERT INTO product_presentations (tenant_id, product_id, name, factor, "
            "barcode, sale_price, purchase_price, is_base, is_active, created_at) "
            "SELECT p.tenant_id, p.id, u.name, 1, p.barcode, NULL, NULL, true, true, "
            "CURRENT_TIMESTAMP FROM products p "
            "JOIN units_of_measure u ON u.id = p.unit_of_measure_id"
        )

    if _on_postgresql():
        op.execute("ALTER TABLE product_presentations ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE product_presentations FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON product_presentations "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )

    # 3. The barcode lives in the presentations
    with op.batch_alter_table("products") as batch:
        batch.drop_constraint("uq_products_tenant_barcode", type_="unique")
        batch.drop_column("barcode")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("barcode", sa.String(length=64), nullable=True))
    with _every_tenant("products", "product_presentations"):
        op.execute(
            "UPDATE products SET barcode = ("
            "SELECT pp.barcode FROM product_presentations pp "
            "WHERE pp.product_id = products.id AND pp.tenant_id = products.tenant_id "
            "AND pp.is_base)"
        )
    with op.batch_alter_table("products") as batch:
        batch.create_unique_constraint(
            "uq_products_tenant_barcode", ["tenant_id", "barcode"]
        )

    op.drop_index(
        "uq_product_presentations_tenant_product_base",
        table_name="product_presentations",
    )
    op.drop_index(
        op.f("ix_product_presentations_product_id"),
        table_name="product_presentations",
    )
    op.drop_index(
        op.f("ix_product_presentations_tenant_id"),
        table_name="product_presentations",
    )
    op.drop_table("product_presentations")

    with op.batch_alter_table("products") as batch:
        batch.alter_column(
            "unit_of_measure_id", existing_type=sa.Integer(), nullable=True
        )
