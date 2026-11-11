"""quotes

Quotes (S5.4, F-07): the proforma a branch hands over for a building job,
numbered per branch (`COT-001-000012`, document_sequences with doc_type QUOTE,
no change needed there), with its customer, its items at the prices of its
lists and the day it is valid until.

- `quotes` and `quote_items`, with row-level security like every business
  table. Composite foreign keys to branches, customers, products and
  presentations; `quote_items.quote_id` is internal (CASCADE).
- `sales.quote_id`, nullable: the quote a POS sale converted, with a composite
  foreign key and one sale per quote (`uq_sales_tenant_quote_id`).

The downgrade drops the quotes and the column: the sales they became stay.

Revision ID: e633ee39eaea
Revises: 924daed89837
Create Date: 2026-11-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn, PercentageColumn, QuantityColumn

# revision identifiers, used by Alembic.
revision: str = "e633ee39eaea"
down_revision: str | None = "924daed89837"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
QUOTE_INDEXES = ("tenant_id", "branch_id", "customer_id", "status")
ITEM_INDEXES = ("tenant_id", "quote_id", "product_id", "presentation_id")


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
        "quotes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("subtotal", MoneyColumn, nullable=False),
        sa.Column("tax", MoneyColumn, nullable=False),
        sa.Column("total", MoneyColumn, nullable=False),
        sa.Column("notes", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("converted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_quotes_tenant_number"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_quotes_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_quotes_branch_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_quotes_customer_tenant",
        ),
        sa.CheckConstraint("valid_until >= issue_date", name="ck_quotes_validity"),
    )
    for column in QUOTE_INDEXES:
        op.create_index(op.f(f"ix_quotes_{column}"), "quotes", [column])
    _isolate("quotes")

    op.create_table(
        "quote_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("quote_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("presentation_id", sa.Integer(), nullable=True),
        sa.Column("quantity", QuantityColumn, nullable=False),
        sa.Column("unit_factor", QuantityColumn, nullable=False),
        sa.Column("unit_price", MoneyColumn, nullable=False),
        sa.Column("discount", PercentageColumn, nullable=False),
        sa.Column("tax_code", sa.String(length=16), nullable=False),
        sa.Column("tax_amount", MoneyColumn, nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_quote_items_product_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "presentation_id"],
            ["product_presentations.tenant_id", "product_presentations.id"],
            name="fk_quote_items_presentation_tenant",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_quote_items_quantity"),
    )
    for column in ITEM_INDEXES:
        op.create_index(op.f(f"ix_quote_items_{column}"), "quote_items", [column])
    _isolate("quote_items")

    with op.batch_alter_table("sales") as batch:
        batch.add_column(sa.Column("quote_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_sales_quote_tenant",
            "quotes",
            ["tenant_id", "quote_id"],
            ["tenant_id", "id"],
        )
        batch.create_unique_constraint(
            "uq_sales_tenant_quote_id", ["tenant_id", "quote_id"]
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("sales") as batch:
        batch.drop_constraint("uq_sales_tenant_quote_id", type_="unique")
        batch.drop_constraint("fk_sales_quote_tenant", type_="foreignkey")
        batch.drop_column("quote_id")
    for column in reversed(ITEM_INDEXES):
        op.drop_index(op.f(f"ix_quote_items_{column}"), table_name="quote_items")
    op.drop_table("quote_items")
    for column in reversed(QUOTE_INDEXES):
        op.drop_index(op.f(f"ix_quotes_{column}"), table_name="quotes")
    op.drop_table("quotes")
