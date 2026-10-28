"""sale invoice status

Whether a confirmed sale's invoice is waiting for the SRI (S3.3): PENDING
since its `sales.confirmed` message reaches the outbox, REJECTED when the SRI
rejects it. A sale with a pending invoice is not cancelled
(INVOICE_IN_PROGRESS). Existing sales stay null: nothing records whether they
were sent.

Revision ID: 6b206e24e504
Revises: f19314b5842a
Create Date: 2026-10-27 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b206e24e504"
down_revision: str | None = "f19314b5842a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sales", sa.Column("invoice_status", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("sales", "invoice_status")
