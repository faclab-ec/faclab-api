"""outbox status and retries

The outbox stops blocking on a broken message (S3.4, G-24). A message is
`pending`, `published` or `failed`: after OUTBOX_MAX_ATTEMPTS it is failed and
no longer holds back its tenant's next messages. `next_attempt_at` is when a
failed attempt is tried again (backoff), and `retried_at`/`retried_by` record
who put a failed message back in the queue. The relay's index covers the
pending messages by tenant, the order it keeps.

Existing rows: those with `published_at` are published, the rest pending.
Downgrading turns failed messages back into pending ones, which the relay of
before S3.4 retries.

Revision ID: 4ddbbb2499e1
Revises: b0f0ab0bf0e3
Create Date: 2026-10-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4ddbbb2499e1"
down_revision: str | None = "b0f0ab0bf0e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "outbox_messages"
INDEX = "ix_outbox_messages_pending"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
    )
    op.add_column(TABLE, sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
    op.add_column(TABLE, sa.Column("retried_at", sa.DateTime(), nullable=True))
    op.add_column(TABLE, sa.Column("retried_by", sa.String(length=64), nullable=True))
    op.execute(
        f"UPDATE {TABLE} SET status = 'published' WHERE published_at IS NOT NULL"
    )
    # The app always sets it; the default was only for the existing rows
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("status", existing_type=sa.String(16), server_default=None)

    op.drop_index(
        INDEX,
        table_name=TABLE,
        postgresql_where=sa.text("published_at IS NULL"),
        sqlite_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        INDEX,
        TABLE,
        ["tenant_id", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        INDEX,
        table_name=TABLE,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        INDEX,
        TABLE,
        ["id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
        sqlite_where=sa.text("published_at IS NULL"),
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("retried_by")
        batch.drop_column("retried_at")
        batch.drop_column("next_attempt_at")
        batch.drop_column("status")
