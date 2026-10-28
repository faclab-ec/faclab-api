"""payment tendered and change

A payment keeps what the customer handed over (`amount_tendered`), what it
applies to the sale (`amount`) and the change given back (S3.3): the cash
register and the invoice's `pagos` count only what was applied.

Existing payments held what was handed over. They start with
`amount_tendered = amount` and no change; in a sale paid in excess, the excess
moves from its cash payments, the latest first, to their change, so what they
apply adds up to the total. A sale overpaid without cash keeps its payments.
The backfill turns FORCE off on `payments` and `sales` while it runs
(faclab_owner, the owner, then skips the policy).

Revision ID: f19314b5842a
Revises: ebc0593c42ca
Create Date: 2026-10-27 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f19314b5842a"
down_revision: str | None = "ebc0593c42ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Money as it is at this revision
MONEY = sa.Numeric(precision=12, scale=6)
BACKFILL_TABLES = ("payments", "sales")

# The excess of each overpaid sale, taken from its cash payments starting with
# the latest: `later` is what the cash payments after this one already took
MOVE_EXCESS_TO_CHANGE = """
WITH excess AS (
    SELECT payments.sale_id, SUM(payments.amount) - sales.total AS excess
    FROM payments JOIN sales ON sales.id = payments.sale_id
    GROUP BY payments.sale_id, sales.total
    HAVING SUM(payments.amount) > sales.total
),
cash AS (
    SELECT payments.id, payments.amount, excess.excess,
        SUM(payments.amount) OVER (
            PARTITION BY payments.sale_id ORDER BY payments.id DESC
        ) - payments.amount AS later
    FROM payments JOIN excess ON excess.sale_id = payments.sale_id
    WHERE payments.payment_method = 'CASH'
),
taken AS (
    SELECT id,
        CASE WHEN amount < excess - later THEN amount ELSE excess - later END
            AS change
    FROM cash
    WHERE excess > later
)
UPDATE payments
SET change = taken.change, amount = payments.amount - taken.change
FROM taken
WHERE payments.id = taken.id
"""


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column("payments", sa.Column("amount_tendered", MONEY, nullable=True))
    op.add_column(
        "payments",
        sa.Column("change", MONEY, nullable=False, server_default="0"),
    )

    postgresql = _on_postgresql()
    if postgresql:
        for table in BACKFILL_TABLES:
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE payments SET amount_tendered = amount")
    op.execute(MOVE_EXCESS_TO_CHANGE)
    if postgresql:
        for table in BACKFILL_TABLES:
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    with op.batch_alter_table("payments") as batch:
        batch.alter_column("amount_tendered", existing_type=MONEY, nullable=False)
        batch.alter_column("change", existing_type=MONEY, server_default=None)


def downgrade() -> None:
    # Back to the amount handed over, as payments were stored before
    postgresql = _on_postgresql()
    if postgresql:
        op.execute("ALTER TABLE payments NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE payments SET amount = amount_tendered")
    if postgresql:
        op.execute("ALTER TABLE payments FORCE ROW LEVEL SECURITY")
    op.drop_column("payments", "change")
    op.drop_column("payments", "amount_tendered")
