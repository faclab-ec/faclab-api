"""branches, emission points and terminals

The tenant's structure (S2.5): branches (SRI establishments, one main branch per
tenant), their emission points and POS terminals, and the branches a membership
is limited to (`user_branch_access`; no rows: all of them).

Every warehouse belongs to a branch. Existing warehouses go to a main branch 001
created for their tenant; the backfill turns FORCE off on `warehouses` while it
runs (faclab_owner, the owner, then skips the policy) and the new tables get
row-level security after it. `user_branch_access` has no policy, like
`memberships`: auth reads it to issue tokens.

Revision ID: c7f9919e67c0
Revises: 798891c3feea
Create Date: 2026-10-19 15:37:25.132434

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f9919e67c0"
down_revision: str | None = "798891c3feea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

# The new business tables
TABLES = ("branches", "emission_points", "pos_terminals")


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("establishment_code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("is_main", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "establishment_code",
            name="uq_branches_tenant_establishment_code",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_branches_tenant_id_id"),
    )
    op.create_index(op.f("ix_branches_tenant_id"), "branches", ["tenant_id"])
    op.create_index(
        "uq_branches_tenant_main",
        "branches",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_main"),
        sqlite_where=sa.text("is_main"),
    )

    op.create_table(
        "emission_points",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_emission_points_branch_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "branch_id",
            "code",
            name="uq_emission_points_tenant_branch_code",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_emission_points_tenant_id_id"),
    )
    op.create_index(
        op.f("ix_emission_points_branch_id"), "emission_points", ["branch_id"]
    )
    op.create_index(
        op.f("ix_emission_points_tenant_id"), "emission_points", ["tenant_id"]
    )

    op.create_table(
        "pos_terminals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("emission_point_id", sa.Integer(), nullable=False),
        sa.Column("default_location_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        _tenant_column(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_pos_terminals_branch_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "default_location_id"],
            ["locations.tenant_id", "locations.id"],
            name="fk_pos_terminals_default_location_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "emission_point_id"],
            ["emission_points.tenant_id", "emission_points.id"],
            name="fk_pos_terminals_emission_point_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "branch_id", "code", name="uq_pos_terminals_tenant_branch_code"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_pos_terminals_tenant_id_id"),
    )
    for column in (
        "branch_id",
        "default_location_id",
        "emission_point_id",
        "tenant_id",
    ):
        op.create_index(op.f(f"ix_pos_terminals_{column}"), "pos_terminals", [column])

    op.create_unique_constraint(
        "uq_memberships_tenant_id_id", "memberships", ["tenant_id", "id"]
    )
    op.create_table(
        "user_branch_access",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "branch_id"],
            ["branches.tenant_id", "branches.id"],
            name="fk_user_branch_access_branch_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_user_branch_access_membership_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id", "branch_id", name="uq_user_branch_access_membership_branch"
        ),
    )
    for column in ("branch_id", "membership_id", "tenant_id"):
        op.create_index(
            op.f(f"ix_user_branch_access_{column}"), "user_branch_access", [column]
        )

    # Every warehouse in a branch: the existing ones go to a new main branch 001
    op.add_column("warehouses", sa.Column("branch_id", sa.Integer(), nullable=True))
    postgresql = _on_postgresql()
    if postgresql:
        op.execute("ALTER TABLE warehouses NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "INSERT INTO branches "
        "(tenant_id, establishment_code, name, is_main, is_active, created_at) "
        "SELECT DISTINCT tenant_id, '001', 'Matriz', true, true, CURRENT_TIMESTAMP "
        "FROM warehouses"
    )
    op.execute(
        "UPDATE warehouses SET branch_id = branches.id FROM branches "
        "WHERE branches.tenant_id = warehouses.tenant_id"
    )
    if postgresql:
        op.execute("ALTER TABLE warehouses FORCE ROW LEVEL SECURITY")
    with op.batch_alter_table("warehouses") as batch:
        batch.alter_column("branch_id", existing_type=sa.Integer(), nullable=False)
        batch.create_index(op.f("ix_warehouses_branch_id"), ["branch_id"])
        batch.create_foreign_key(
            "fk_warehouses_branch_tenant",
            "branches",
            ["tenant_id", "branch_id"],
            ["tenant_id", "id"],
        )

    if postgresql:
        for table in TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {POLICY} ON {table} "
                f"USING ({TENANT}) WITH CHECK ({TENANT})"
            )


def downgrade() -> None:
    """Downgrade schema. The tables' policies go with them."""
    with op.batch_alter_table("warehouses") as batch:
        batch.drop_constraint("fk_warehouses_branch_tenant", type_="foreignkey")
        batch.drop_index(op.f("ix_warehouses_branch_id"))
        batch.drop_column("branch_id")
    op.drop_table("user_branch_access")
    op.drop_constraint("uq_memberships_tenant_id_id", "memberships", type_="unique")
    op.drop_table("pos_terminals")
    op.drop_table("emission_points")
    op.drop_table("branches")
