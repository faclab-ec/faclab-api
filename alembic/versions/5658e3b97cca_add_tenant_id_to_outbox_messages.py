"""add tenant_id to outbox messages

Nullable: the messages already written have no tenant. The S2.3 baseline makes
it NOT NULL.

Revision ID: 5658e3b97cca
Revises: 97b4bc110bcb
Create Date: 2026-10-16 01:48:33.402272

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5658e3b97cca"
down_revision: str | None = "97b4bc110bcb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("outbox_messages", sa.Column("tenant_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("outbox_messages", "tenant_id")
