"""tenant composite foreign keys

Every reference a route can fill becomes `(tenant_id, x_id)` → `xs(tenant_id, id)`
(S2.4): PostgreSQL checks foreign keys without row-level security, so a
single-column key would accept another tenant's id. The referenced tables get
`UNIQUE (tenant_id, id)` first; a key that set the column to NULL now names it
(`SET NULL (x_id)`) so it never nulls `tenant_id`.

Revision ID: 3df55a3cc8fb
Revises: 80ccdab134c7
Create Date: 2026-10-19 01:09:36.096254

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3df55a3cc8fb"
down_revision: str | None = "80ccdab134c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Targets of the new composite keys
UNIQUES = ("categories", "units_of_measure", "warehouses", "lots")

# (table, column, referenced table, ondelete of the single-column key)
RELATIONS = (
    ("products", "category_id", "categories", None),
    ("products", "unit_of_measure_id", "units_of_measure", None),
    ("locations", "warehouse_id", "warehouses", None),
    ("lots", "product_id", "products", "RESTRICT"),
    ("serial_numbers", "product_id", "products", "RESTRICT"),
    ("serial_numbers", "lot_id", "lots", "SET NULL"),
    ("serial_numbers", "location_id", "locations", "SET NULL"),
    ("inventory_adjustments", "warehouse_id", "warehouses", None),
    ("adjustment_items", "product_id", "products", None),
    ("adjustment_items", "location_id", "locations", None),
    ("adjustment_items", "lot_id", "lots", "SET NULL"),
    ("stock_transfer_items", "product_id", "products", None),
    ("stock_transfer_items", "lot_id", "lots", "SET NULL"),
    ("customer_contacts", "customer_id", "customers", "CASCADE"),
    ("supplier_contacts", "supplier_id", "suppliers", "CASCADE"),
    ("supplier_products", "supplier_id", "suppliers", "CASCADE"),
    ("supplier_products", "product_id", "products", "CASCADE"),
    ("purchase_order_items", "product_id", "products", "RESTRICT"),
    ("purchase_receipt_items", "location_id", "locations", "SET NULL"),
)


def _composite_name(table: str, column: str) -> str:
    return f"fk_{table}_{column.removesuffix('_id')}_tenant"


def _composite_ondelete(column: str, ondelete: str | None) -> str | None:
    return f"SET NULL ({column})" if ondelete == "SET NULL" else ondelete


def upgrade() -> None:
    """Upgrade schema."""
    for table in UNIQUES:
        op.create_unique_constraint(
            f"uq_{table}_tenant_id_id", table, ["tenant_id", "id"]
        )
    for table, column, _, _ in RELATIONS:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
    for table, column, referred, ondelete in RELATIONS:
        op.create_foreign_key(
            _composite_name(table, column),
            table,
            referred,
            ["tenant_id", column],
            ["tenant_id", "id"],
            ondelete=_composite_ondelete(column, ondelete),
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, _, _ in RELATIONS:
        op.drop_constraint(_composite_name(table, column), table, type_="foreignkey")
    for table, column, referred, ondelete in RELATIONS:
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            referred,
            [column],
            ["id"],
            ondelete=ondelete,
        )
    for table in UNIQUES:
        op.drop_constraint(f"uq_{table}_tenant_id_id", table, type_="unique")
