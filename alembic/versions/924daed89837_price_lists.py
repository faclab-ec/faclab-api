"""price lists

Price lists (S5.3, F-06): retail, wholesale or volume lists of each company,
assigned to a customer or a branch, with the price of a presentation of a
product from a quantity (0 is the list's base price, more is a volume tier).

- `price_lists` and `price_list_items`, with row-level security like every
  business table. Every company gets its general list ("General",
  `is_default`): its base price is the product's and it only holds tiers, so no
  price is copied.
- `customers.price_list_id` and `branches.price_list_id`, nullable, with
  composite foreign keys: deleting an assigned list answers RECORD_IN_USE.

The downgrade drops the lists, their prices and both assignments: every sale
takes the product's price again.

Revision ID: 924daed89837
Revises: f6c2d84e1a97
Create Date: 2026-11-10 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn, QuantityColumn

# revision identifiers, used by Alembic.
revision: str = "924daed89837"
down_revision: str | None = "f6c2d84e1a97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
ASSIGNED = ("customers", "branches")


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _isolate(table: str) -> None:
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "price_lists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_price_lists_tenant_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_price_lists_tenant_id_id"),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="ck_price_lists_validity",
        ),
        sa.CheckConstraint(
            "NOT is_default OR (is_active AND valid_from IS NULL AND valid_to IS NULL)",
            name="ck_price_lists_default",
        ),
    )
    op.create_index(op.f("ix_price_lists_tenant_id"), "price_lists", ["tenant_id"])
    op.create_index(
        "uq_price_lists_tenant_default",
        "price_lists",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )
    # Every company has its general list (tenants has no row-level security)
    op.execute(
        "INSERT INTO price_lists (tenant_id, name, is_default, is_active, created_at) "
        "SELECT id, 'General', true, true, CURRENT_TIMESTAMP FROM tenants"
    )
    _isolate("price_lists")

    op.create_table(
        "price_list_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("price_list_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("presentation_id", sa.Integer(), nullable=False),
        sa.Column("min_quantity", QuantityColumn, nullable=False),
        sa.Column("price", MoneyColumn, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "price_list_id"],
            ["price_lists.tenant_id", "price_lists.id"],
            name="fk_price_list_items_price_list_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_price_list_items_product_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "presentation_id"],
            ["product_presentations.tenant_id", "product_presentations.id"],
            name="fk_price_list_items_presentation_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "price_list_id",
            "presentation_id",
            "min_quantity",
            name="uq_price_list_items_tenant_list_presentation_min",
        ),
        sa.CheckConstraint("price >= 0", name="ck_price_list_items_price"),
        sa.CheckConstraint(
            "min_quantity >= 0", name="ck_price_list_items_min_quantity"
        ),
    )
    for column in ("tenant_id", "price_list_id", "product_id", "presentation_id"):
        op.create_index(
            op.f(f"ix_price_list_items_{column}"), "price_list_items", [column]
        )
    _isolate("price_list_items")

    for table in ASSIGNED:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("price_list_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_price_list_tenant",
                "price_lists",
                ["tenant_id", "price_list_id"],
                ["tenant_id", "id"],
            )
        op.create_index(op.f(f"ix_{table}_price_list_id"), table, ["price_list_id"])


def downgrade() -> None:
    """Downgrade schema."""
    for table in ASSIGNED:
        op.drop_index(op.f(f"ix_{table}_price_list_id"), table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_price_list_tenant", type_="foreignkey")
            batch.drop_column("price_list_id")
    for column in ("presentation_id", "product_id", "price_list_id", "tenant_id"):
        op.drop_index(
            op.f(f"ix_price_list_items_{column}"), table_name="price_list_items"
        )
    op.drop_table("price_list_items")
    op.drop_index("uq_price_lists_tenant_default", table_name="price_lists")
    op.drop_index(op.f("ix_price_lists_tenant_id"), table_name="price_lists")
    op.drop_table("price_lists")
