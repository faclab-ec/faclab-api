"""shift closings

The formal Z closing of a POS shift (S5.9, F-10):

- `pos_shift_closings`: written in the transaction that closes a shift, one per
  shift. Its number is a correlative per terminal (`Z-001-CAJA-01-000012`); it
  keeps what the shift moved when it closed (sales, refunds, the cash and its
  components, the products sold as JSON), who closed it and the threshold over
  which a difference needed a justification. The Z report reads it instead of
  recalculating. Its terminal and branch are composite keys, like the shift's;
  its shift is an internal key (the shift being closed).
- `pos_shift_closing_lines`: the count of each payment method (what it moved,
  expected, counted, difference and justification; CREDIT only informs). An
  internal key to its closing (the closing being written).

Both get row-level security like every business table, and they can't be
changed: the default privileges gave faclab_app and faclab_worker UPDATE and
DELETE on them, this revokes them (INSERT and SELECT stay), as for audit_log.
Shifts closed before this revision have no closing: their Z is still calculated.

The downgrade drops both tables: the Z report is calculated again.

Revision ID: 882414a85890
Revises: f3a8c5d27e41
Create Date: 2026-11-16 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "882414a85890"
down_revision: str | None = "f3a8c5d27e41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
INDEXES = {
    "pos_shift_closings": ("tenant_id", "shift_id", "terminal_id", "branch_id"),
    "pos_shift_closing_lines": ("tenant_id", "closing_id"),
}


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _money(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Numeric(18, 6), nullable=nullable)


def _indexes_isolation_and_immutability(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )
        op.execute(f"REVOKE UPDATE, DELETE ON {table} FROM faclab_app, faclab_worker")


def _drop(table: str) -> None:
    for column in reversed(INDEXES[table]):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pos_shift_closings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column(
            "shift_id", sa.Integer(), sa.ForeignKey("pos_shifts.id"), nullable=False
        ),
        sa.Column("terminal_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("cashier_name", sa.String(length=128), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.Column("closed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "closed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_pos_shift_closings_closed_by_user"),
            nullable=True,
        ),
        _money("opening_balance"),
        sa.Column("sales_count", sa.Integer(), nullable=False),
        _money("sales_subtotal"),
        _money("sales_tax"),
        _money("sales_discount"),
        _money("sales_total"),
        sa.Column("refunds_count", sa.Integer(), nullable=False),
        _money("refunds_total"),
        _money("cash_sales"),
        _money("cash_refunds"),
        _money("customer_payments"),
        _money("cash_in"),
        _money("cash_out"),
        _money("justification_threshold"),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("items_sold", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "shift_id", name="uq_pos_shift_closings_tenant_shift_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "terminal_id",
            "sequence",
            name="uq_pos_shift_closings_tenant_terminal_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "terminal_id"],
            ["pos_terminals.tenant_id", "pos_terminals.id"],
            name="fk_pos_shift_closings_terminal_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_shift_closings_branch_tenant",
        ),
    )
    _indexes_isolation_and_immutability("pos_shift_closings")

    op.create_table(
        "pos_shift_closing_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column(
            "closing_id",
            sa.Integer(),
            sa.ForeignKey("pos_shift_closings.id"),
            nullable=False,
        ),
        sa.Column("payment_method", sa.String(length=16), nullable=False),
        sa.Column("payments_count", sa.Integer(), nullable=False),
        _money("payments_total"),
        sa.Column("customer_payments_count", sa.Integer(), nullable=False),
        _money("customer_payments_total"),
        _money("refunds_total"),
        _money("expected", nullable=True),
        _money("counted", nullable=True),
        _money("difference", nullable=True),
        sa.Column("justification", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "closing_id",
            "payment_method",
            name="uq_pos_shift_closing_lines_tenant_closing_method",
        ),
    )
    _indexes_isolation_and_immutability("pos_shift_closing_lines")


def downgrade() -> None:
    """Downgrade schema. The tables' policies and grants go with them."""
    _drop("pos_shift_closing_lines")
    _drop("pos_shift_closings")
