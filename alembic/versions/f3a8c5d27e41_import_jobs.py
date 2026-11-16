"""import jobs

Bulk import of initial data (S5.8, F-05):

- `import_jobs`: a file a user uploaded to import (its template, mode, size and
  who uploaded it), what its rows would do when it was validated and how far the
  worker got (cursor, rows per action, the row that stopped it).
- `import_job_rows`: each row of the file as it came (JSON by template header),
  its action, its errors and the record it wrote. An internal key to its job
  (the job being created), deleted with it.

Both have row-level security like every business table. Opening stock enters as
adjustments with the new reason `initial_balance` (a text column: no change).

The downgrade drops both tables; what the imports wrote stays as ordinary data.

Revision ID: f3a8c5d27e41
Revises: c2e7b5a90f31
Create Date: 2026-11-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a8c5d27e41"
down_revision: str | None = "c2e7b5a90f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
INDEXES = {
    "import_jobs": ("tenant_id",),
    "import_job_rows": ("tenant_id", "job_id"),
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


def _indexes_and_isolation(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def _drop(table: str) -> None:
    for column in reversed(INDEXES[table]):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("planned", sa.JSON(), nullable=False),
        sa.Column("done", sa.JSON(), nullable=False),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("cursor_row", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("user_name", sa.String(length=64), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("failed_row", sa.Integer(), nullable=True),
        sa.Column("failure", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_jobs_status_confirmed_at",
        "import_jobs",
        ["status", "confirmed_at"],
    )
    _indexes_and_isolation("import_jobs")

    op.create_table(
        "import_job_rows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_id",
            "row_number",
            name="uq_import_job_rows_tenant_job_row",
        ),
    )
    _indexes_and_isolation("import_job_rows")


def downgrade() -> None:
    """Downgrade schema."""
    _drop("import_job_rows")
    op.drop_index("ix_import_jobs_status_confirmed_at", table_name="import_jobs")
    _drop("import_jobs")
