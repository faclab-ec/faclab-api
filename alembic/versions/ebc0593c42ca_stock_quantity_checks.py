"""stock quantity checks

No stock row below zero or reserving more than it holds (S3.2): the domain
rejects those writes with INSUFFICIENT_STOCK and these CHECKs are the last
barrier. The migration doesn't touch data: a database that already has such
rows (e.g. negative stock from an OUT without a row, before S3.2) fails here
with the constraint's name, and those rows are corrected by hand first.

Revision ID: ebc0593c42ca
Revises: 4e07e6cd9e67
Create Date: 2026-10-27 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ebc0593c42ca"
down_revision: str | None = "4e07e6cd9e67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_stocks_quantity_non_negative", "stocks", "quantity >= 0"
    )
    op.create_check_constraint(
        "ck_stocks_reserved_quantity_range",
        "stocks",
        "reserved_quantity >= 0 AND reserved_quantity <= quantity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stocks_reserved_quantity_range", "stocks", type_="check")
    op.drop_constraint("ck_stocks_quantity_non_negative", "stocks", type_="check")
