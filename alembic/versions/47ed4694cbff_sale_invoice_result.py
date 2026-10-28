"""sale invoice result

The sale shows the result of its invoice (S3.4, G-21): `invoice_status` gets
AUTHORIZED, `invoice_id` is the last invoice faclab-invoicing reported a result
for (so a repeated rejection of an invoice already rejected doesn't undo a
resend) and `invoice_rejection_reason` keeps the SRI's messages.

Invoiced sales become AUTHORIZED. The backfill turns FORCE off while it runs
(faclab_owner, the owner, then skips the policy). Downgrading clears it again.

Revision ID: 47ed4694cbff
Revises: 36ec1f2d47ad
Create Date: 2026-10-28 10:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "47ed4694cbff"
down_revision: str | None = "36ec1f2d47ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _without_force(statement: str) -> None:
    postgresql = op.get_bind().dialect.name == "postgresql"
    if postgresql:
        op.execute("ALTER TABLE sales NO FORCE ROW LEVEL SECURITY")
    op.execute(statement)
    if postgresql:
        op.execute("ALTER TABLE sales FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sales", sa.Column("invoice_id", sa.String(length=64), nullable=True))
    op.add_column(
        "sales",
        sa.Column("invoice_rejection_reason", sa.String(length=1000), nullable=True),
    )
    _without_force(
        "UPDATE sales SET invoice_status = 'AUTHORIZED' WHERE status = 'INVOICED'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    _without_force(
        "UPDATE sales SET invoice_status = NULL WHERE invoice_status = 'AUTHORIZED'"
    )
    with op.batch_alter_table("sales") as batch:
        batch.drop_column("invoice_rejection_reason")
        batch.drop_column("invoice_id")
