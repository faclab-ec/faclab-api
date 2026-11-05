"""credit notes

Credit notes asked of faclab-invoicing and their result (S4.5, G-11, G-20):

- `credit_notes`: one per refund of an invoiced sale, and one per invoice the SRI
  authorized after its sale was cancelled (no refund). Row-level security like
  every business table. `invoice_id` and `document_id` point at
  faclab-invoicing, not at a table of this database.
- `sales.invoice_status` takes `CREDITED`: it is a String, nothing changes there.

Revision ID: a3d9e1c47b52
Revises: 5c1d2e8a9f30
Create Date: 2026-11-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn

# revision identifiers, used by Alembic.
revision: str = "a3d9e1c47b52"
down_revision: str | None = "5c1d2e8a9f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "credit_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sale_id", sa.Integer(), sa.ForeignKey("sales.id"), nullable=False),
        sa.Column(
            "refund_id", sa.Integer(), sa.ForeignKey("pos_refunds.id"), nullable=True
        ),
        sa.Column("invoice_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("subtotal", MoneyColumn, nullable=False),
        sa.Column("tax", MoneyColumn, nullable=False),
        sa.Column("total", MoneyColumn, nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("access_code", sa.String(length=49), nullable=True),
        sa.Column("authorized_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=1000), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_notes_tenant_id"), "credit_notes", ["tenant_id"])
    op.create_index(op.f("ix_credit_notes_sale_id"), "credit_notes", ["sale_id"])
    op.create_index(op.f("ix_credit_notes_refund_id"), "credit_notes", ["refund_id"])
    op.create_index(op.f("ix_credit_notes_status"), "credit_notes", ["status"])
    op.create_index(
        "uq_credit_notes_tenant_refund",
        "credit_notes",
        ["tenant_id", "refund_id"],
        unique=True,
        postgresql_where=sa.text("refund_id IS NOT NULL"),
        sqlite_where=sa.text("refund_id IS NOT NULL"),
    )
    op.create_index(
        "uq_credit_notes_tenant_cancelled_sale",
        "credit_notes",
        ["tenant_id", "sale_id"],
        unique=True,
        postgresql_where=sa.text("refund_id IS NULL"),
        sqlite_where=sa.text("refund_id IS NULL"),
    )

    if _on_postgresql():
        op.execute("ALTER TABLE credit_notes ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE credit_notes FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON credit_notes "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema. The table's policy and grants go with it. A sale whose
    invoice was credited keeps it as authorized: the previous version doesn't
    know CREDITED."""
    if _on_postgresql():
        op.execute("ALTER TABLE sales NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE sales SET invoice_status = 'AUTHORIZED' "
        "WHERE invoice_status = 'CREDITED'"
    )
    if _on_postgresql():
        op.execute("ALTER TABLE sales FORCE ROW LEVEL SECURITY")
    op.drop_index("uq_credit_notes_tenant_cancelled_sale", table_name="credit_notes")
    op.drop_index("uq_credit_notes_tenant_refund", table_name="credit_notes")
    op.drop_index(op.f("ix_credit_notes_status"), table_name="credit_notes")
    op.drop_index(op.f("ix_credit_notes_refund_id"), table_name="credit_notes")
    op.drop_index(op.f("ix_credit_notes_sale_id"), table_name="credit_notes")
    op.drop_index(op.f("ix_credit_notes_tenant_id"), table_name="credit_notes")
    op.drop_table("credit_notes")
