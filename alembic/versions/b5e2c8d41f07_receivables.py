"""receivables

Credit sales and accounts receivable (S5.5, F-08):

- `payments.term_days`, nullable: the days a CREDIT payment gives the customer
  (its payment terms), the invoice's `plazo`. CREDIT is a new value of
  `payment_method`, a text column: no change needed there.
- `receivables`: one per sale on credit, with its balance and due date.
  Composite foreign keys to customers and branches; `sale_id` is internal (the
  sale being confirmed) and unique per tenant.
- `customer_payments`: payments on account, numbered per tenant
  (`AB-2026-0001`, document_sequences with doc_type CUSTOMER_PAYMENT, no change
  needed there), at a terminal's open shift (`shift_id`, internal) or outside the
  cash register. Composite foreign keys to customers, branches and terminals.
- `receivable_applications`: what a payment or a refund took off a receivable,
  with a composite key to its receivable and internal ones to the payment and
  the refund.

Every new table has row-level security like every business table.

The downgrade drops the tables and the column. CREDIT payments of sales and
refunds become OTHER, so the code before S5.5 still reads them: the sales stay,
without their receivables, and their payment status stays as it was.

Revision ID: b5e2c8d41f07
Revises: e633ee39eaea
Create Date: 2026-11-11 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from src.shared.infra.precision import MoneyColumn

# revision identifiers, used by Alembic.
revision: str = "b5e2c8d41f07"
down_revision: str | None = "e633ee39eaea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
RECEIVABLE_INDEXES = (
    "tenant_id",
    "customer_id",
    "sale_id",
    "branch_id",
    "due_on",
    "status",
)
PAYMENT_INDEXES = ("tenant_id", "customer_id", "branch_id", "terminal_id", "shift_id")
APPLICATION_INDEXES = ("tenant_id", "receivable_id", "customer_payment_id", "refund_id")


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


def _across_tenants(table: str, statement: str) -> None:
    """A data change on every tenant's rows: FORCE binds the owner too"""
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("term_days", sa.Integer(), nullable=True))

    op.create_table(
        "receivables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("balance", MoneyColumn, nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("term_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "sale_id", name="uq_receivables_tenant_sale_id"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_receivables_tenant_id_id"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_receivables_customer_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_receivables_branch_tenant",
        ),
        sa.CheckConstraint(
            "amount > 0 AND balance >= 0 AND balance <= amount",
            name="ck_receivables_balance",
        ),
    )
    for column in RECEIVABLE_INDEXES:
        op.create_index(op.f(f"ix_receivables_{column}"), "receivables", [column])
    _isolate("receivables")

    op.create_table(
        "customer_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("payment_method", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=False),
        sa.Column("received_by", sa.String(length=64), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("terminal_id", sa.Integer(), nullable=True),
        sa.Column("shift_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "number", name="uq_customer_payments_tenant_number"
        ),
        sa.ForeignKeyConstraint(["shift_id"], ["pos_shifts.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_payments_customer_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_customer_payments_branch_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_customer_payments_terminal_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_customer_payments_amount"),
    )
    for column in PAYMENT_INDEXES:
        op.create_index(
            op.f(f"ix_customer_payments_{column}"), "customer_payments", [column]
        )
    _isolate("customer_payments")

    op.create_table(
        "receivable_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("receivable_id", sa.Integer(), nullable=False),
        sa.Column("amount", MoneyColumn, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("customer_payment_id", sa.Integer(), nullable=True),
        sa.Column("refund_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["customer_payment_id"], ["customer_payments.id"]),
        sa.ForeignKeyConstraint(["refund_id"], ["pos_refunds.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receivable_id"],
            ["receivables.tenant_id", "receivables.id"],
            name="fk_receivable_applications_receivable_tenant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_receivable_applications_amount"),
        sa.CheckConstraint(
            "(kind = 'PAYMENT' AND customer_payment_id IS NOT NULL "
            "AND refund_id IS NULL) OR "
            "(kind = 'REFUND' AND refund_id IS NOT NULL "
            "AND customer_payment_id IS NULL)",
            name="ck_receivable_applications_source",
        ),
    )
    for column in APPLICATION_INDEXES:
        op.create_index(
            op.f(f"ix_receivable_applications_{column}"),
            "receivable_applications",
            [column],
        )
    _isolate("receivable_applications")


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(APPLICATION_INDEXES):
        op.drop_index(
            op.f(f"ix_receivable_applications_{column}"),
            table_name="receivable_applications",
        )
    op.drop_table("receivable_applications")
    for column in reversed(PAYMENT_INDEXES):
        op.drop_index(
            op.f(f"ix_customer_payments_{column}"), table_name="customer_payments"
        )
    op.drop_table("customer_payments")
    for column in reversed(RECEIVABLE_INDEXES):
        op.drop_index(op.f(f"ix_receivables_{column}"), table_name="receivables")
    op.drop_table("receivables")

    # The code before S5.5 doesn't know CREDIT
    _across_tenants(
        "payments",
        "UPDATE payments SET payment_method = 'OTHER', term_days = NULL "
        "WHERE payment_method = 'CREDIT'",
    )
    _across_tenants(
        "pos_refund_payments",
        "UPDATE pos_refund_payments SET payment_method = 'OTHER' "
        "WHERE payment_method = 'CREDIT'",
    )
    _across_tenants(
        "document_sequences",
        "DELETE FROM document_sequences WHERE doc_type = 'CUSTOMER_PAYMENT'",
    )
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("term_days")
