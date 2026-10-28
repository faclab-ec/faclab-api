"""purchase order sequence

Purchase orders are numbered with the tenant's counter in
`document_sequences` (S3.3, ADR-0012) instead of `MAX()` over the existing
numbers, which collided under concurrency (G-33). A tenant's counter has no
branch: `branch_id` becomes nullable and the partial unique index
`uq_document_sequences_tenant_doc_type` keeps one per type (NULLs never
collide in `uq_document_sequences_tenant_branch_doc_type`).

The counter is continuous (it doesn't go back to 1 each year), so each
tenant's starts at the highest sequence among its `PO-<year>-<n>` numbers and
no number repeats. The backfill turns FORCE off on both tables while it runs
(faclab_owner, the owner, then skips the policy).

Revision ID: b0f0ab0bf0e3
Revises: 734b22d691ca
Create Date: 2026-10-27 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0f0ab0bf0e3"
down_revision: str | None = "734b22d691ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_document_sequences_tenant_doc_type"
BACKFILL_TABLES = ("document_sequences", "purchase_orders")
# `PO-2026-` is 8 characters: the sequence starts at the 9th
START_COUNTERS = """
INSERT INTO document_sequences (tenant_id, branch_id, doc_type, last_value)
SELECT tenant_id, NULL, 'PURCHASE_ORDER',
    MAX(CAST(SUBSTR(order_number, 9) AS INTEGER))
FROM purchase_orders
WHERE {numbered}
GROUP BY tenant_id
"""


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _without_force(postgresql: bool, statement: str) -> None:
    if postgresql:
        for table in BACKFILL_TABLES:
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    if postgresql:
        for table in BACKFILL_TABLES:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    with op.batch_alter_table("document_sequences") as batch:
        batch.alter_column("branch_id", existing_type=sa.Integer(), nullable=True)
    op.create_index(
        INDEX,
        "document_sequences",
        ["tenant_id", "doc_type"],
        unique=True,
        postgresql_where=sa.text("branch_id IS NULL"),
        sqlite_where=sa.text("branch_id IS NULL"),
    )

    postgresql = _on_postgresql()
    numbered = (
        "order_number ~ '^PO-[0-9]{4}-[0-9]+$'"
        if postgresql
        else "order_number GLOB 'PO-[0-9][0-9][0-9][0-9]-[0-9]*'"
    )
    _without_force(postgresql, START_COUNTERS.format(numbered=numbered))


def downgrade() -> None:
    # Orders go back to MAX() over their numbers
    _without_force(
        _on_postgresql(), "DELETE FROM document_sequences WHERE branch_id IS NULL"
    )
    op.drop_index(INDEX, table_name="document_sequences")
    with op.batch_alter_table("document_sequences") as batch:
        batch.alter_column("branch_id", existing_type=sa.Integer(), nullable=False)
