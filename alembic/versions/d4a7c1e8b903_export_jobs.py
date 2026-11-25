"""export jobs

Export of a company's data (S8.7, LOPDP): `export_jobs` keeps who asked for it,
how far the worker got and the ZIP it left in `DATA_EXPORT_DIR`. Row-level
security like every business table.

The downgrade drops the table; the ZIPs stay on the worker's volume until they
are deleted by hand.

Revision ID: d4a7c1e8b903
Revises: b8c3d1f6a2e5
Create Date: 2026-11-25 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a7c1e8b903"
down_revision: str | None = "b8c3d1f6a2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_name", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("file_name", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("failure", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_export_jobs_tenant_id"), "export_jobs", ["tenant_id"])
    op.create_index("ix_export_jobs_status_id", "export_jobs", ["status", "id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE export_jobs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE export_jobs FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON export_jobs USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_export_jobs_status_id", table_name="export_jobs")
    op.drop_index(op.f("ix_export_jobs_tenant_id"), table_name="export_jobs")
    op.drop_table("export_jobs")
