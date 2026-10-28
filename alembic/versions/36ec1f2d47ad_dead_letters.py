"""dead letters

The messages the Kafka consumer couldn't process after its retries (S3.4,
G-25): kept with their headers and the error, so the partition goes on and
they can be reprocessed (`python -m src.background.cli dead-letter-reprocess`).

Infrastructure like `outbox_messages`: no row-level security, and only
faclab_worker (the consumer and the platform CLI) reads and writes it; the API's
faclab_app has no privilege on it. `tenant_id` is the tenant of the message,
when it carried one.

Revision ID: 36ec1f2d47ad
Revises: 4ddbbb2499e1
Create Date: 2026-10-28 10:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "36ec1f2d47ad"
down_revision: str | None = "4ddbbb2499e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("consumer_group", sa.String(length=128), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("kafka_partition", sa.Integer(), nullable=False),
        sa.Column("kafka_offset", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reprocessed_at", sa.DateTime(), nullable=True),
        sa.Column("reprocessed_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "consumer_group",
            "topic",
            "kafka_partition",
            "kafka_offset",
            name="uq_dead_letters_message",
        ),
    )
    op.create_index(
        "ix_dead_letters_pending",
        "dead_letters",
        ["id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    if _on_postgresql():
        # The default privileges gave it to both roles: only the worker keeps it
        op.execute("REVOKE ALL ON dead_letters FROM faclab_app")
        op.execute("REVOKE ALL ON SEQUENCE dead_letters_id_seq FROM faclab_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_dead_letters_pending",
        table_name="dead_letters",
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.drop_table("dead_letters")
