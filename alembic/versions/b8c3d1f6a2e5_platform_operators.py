"""platform operators

The platform console (S8.5): `platform_operators` says which users of the
platform's team may log into `/api/platform`. A platform table (no tenant, no
row-level security): faclab_app reads it at the console's login, rows are only
inserted by the platform's CLI (faclab_app has no INSERT, UPDATE or DELETE). Its downgrade drops it.

Revision ID: b8c3d1f6a2e5
Revises: a22a34717c3e
Create Date: 2026-11-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c3d1f6a2e5"
down_revision: str | None = "a22a34717c3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "platform_operators",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    if op.get_bind().dialect.name == "postgresql":
        # The API only reads who is an operator; the platform's CLI
        # (faclab_worker) is the one that adds them
        op.execute(
            "REVOKE INSERT, UPDATE, DELETE ON platform_operators FROM faclab_app"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("platform_operators")
