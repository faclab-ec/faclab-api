"""pos by terminal

The POS by terminal (S2.6): a shift belongs to a terminal (at most one open per
terminal, a partial unique index) and to the user who opened it; POS sales and
refunds record their branch, emission point and terminal and a number per
branch from `document_sequences` (ADR-0012).

The new columns are null in the rows from before: those shifts, sales and
refunds have no terminal. `document_sequences` gets row-level security like
every business table.

Revision ID: 654849d8d497
Revises: c7f9919e67c0
Create Date: 2026-10-19 21:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "654849d8d497"
down_revision: str | None = "c7f9919e67c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _composite(batch, name: str, column: str, table: str) -> None:
    batch.create_foreign_key(name, table, ["tenant_id", column], ["tenant_id", "id"])


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_sequences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_document_sequences_branch_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "branch_id",
            "doc_type",
            name="uq_document_sequences_tenant_branch_doc_type",
        ),
    )
    op.create_index(
        op.f("ix_document_sequences_tenant_id"), "document_sequences", ["tenant_id"]
    )

    with op.batch_alter_table("pos_shifts") as batch:
        batch.add_column(sa.Column("terminal_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("opened_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("closed_by", sa.String(length=128), nullable=True))
        batch.create_index(op.f("ix_pos_shifts_terminal_id"), ["terminal_id"])
        batch.create_index(op.f("ix_pos_shifts_branch_id"), ["branch_id"])
        _composite(
            batch, "fk_pos_shifts_terminal_tenant", "terminal_id", "pos_terminals"
        )
        _composite(batch, "fk_pos_shifts_branch_tenant", "branch_id", "branches")
        batch.create_foreign_key(
            "fk_pos_shifts_opened_by_user", "users", ["opened_by_user_id"], ["id"]
        )
    # At most one open shift per terminal, also between concurrent openings
    op.create_index(
        "uq_pos_shifts_tenant_terminal_open",
        "pos_shifts",
        ["tenant_id", "terminal_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )

    with op.batch_alter_table("sales") as batch:
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("emission_point_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("terminal_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("number", sa.String(length=32), nullable=True))
        for column in ("branch_id", "emission_point_id", "terminal_id"):
            batch.create_index(op.f(f"ix_sales_{column}"), [column])
        _composite(batch, "fk_sales_branch_tenant", "branch_id", "branches")
        _composite(
            batch,
            "fk_sales_emission_point_tenant",
            "emission_point_id",
            "emission_points",
        )
        _composite(batch, "fk_sales_terminal_tenant", "terminal_id", "pos_terminals")
        batch.create_unique_constraint(
            "uq_sales_tenant_branch_number", ["tenant_id", "branch_id", "number"]
        )

    with op.batch_alter_table("pos_refunds") as batch:
        batch.add_column(sa.Column("branch_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("terminal_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("number", sa.String(length=32), nullable=True))
        batch.create_index(op.f("ix_pos_refunds_branch_id"), ["branch_id"])
        batch.create_index(op.f("ix_pos_refunds_terminal_id"), ["terminal_id"])
        _composite(batch, "fk_pos_refunds_branch_tenant", "branch_id", "branches")
        _composite(
            batch, "fk_pos_refunds_terminal_tenant", "terminal_id", "pos_terminals"
        )
        batch.create_unique_constraint(
            "uq_pos_refunds_tenant_branch_number",
            ["tenant_id", "branch_id", "number"],
        )

    op.create_index(
        "ix_movements_reference", "movements", ["reference_type", "reference_id"]
    )

    if _on_postgresql():
        op.execute("ALTER TABLE document_sequences ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE document_sequences FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON document_sequences "
            f"USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema. The table's policy goes with it."""
    op.drop_index("ix_movements_reference", table_name="movements")

    with op.batch_alter_table("pos_refunds") as batch:
        batch.drop_constraint("uq_pos_refunds_tenant_branch_number", type_="unique")
        batch.drop_constraint("fk_pos_refunds_terminal_tenant", type_="foreignkey")
        batch.drop_constraint("fk_pos_refunds_branch_tenant", type_="foreignkey")
        batch.drop_index(op.f("ix_pos_refunds_terminal_id"))
        batch.drop_index(op.f("ix_pos_refunds_branch_id"))
        batch.drop_column("number")
        batch.drop_column("terminal_id")
        batch.drop_column("branch_id")

    with op.batch_alter_table("sales") as batch:
        batch.drop_constraint("uq_sales_tenant_branch_number", type_="unique")
        batch.drop_constraint("fk_sales_terminal_tenant", type_="foreignkey")
        batch.drop_constraint("fk_sales_emission_point_tenant", type_="foreignkey")
        batch.drop_constraint("fk_sales_branch_tenant", type_="foreignkey")
        for column in ("branch_id", "emission_point_id", "terminal_id"):
            batch.drop_index(op.f(f"ix_sales_{column}"))
        batch.drop_column("number")
        batch.drop_column("terminal_id")
        batch.drop_column("emission_point_id")
        batch.drop_column("branch_id")

    op.drop_index("uq_pos_shifts_tenant_terminal_open", table_name="pos_shifts")
    with op.batch_alter_table("pos_shifts") as batch:
        batch.drop_constraint("fk_pos_shifts_opened_by_user", type_="foreignkey")
        batch.drop_constraint("fk_pos_shifts_branch_tenant", type_="foreignkey")
        batch.drop_constraint("fk_pos_shifts_terminal_tenant", type_="foreignkey")
        batch.drop_index(op.f("ix_pos_shifts_branch_id"))
        batch.drop_index(op.f("ix_pos_shifts_terminal_id"))
        batch.drop_column("closed_by")
        batch.drop_column("opened_by_user_id")
        batch.drop_column("branch_id")
        batch.drop_column("terminal_id")

    op.drop_table("document_sequences")
