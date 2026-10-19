"""row level security

Row-level security on every business table (S2.4), the second barrier after the
application's tenant filter: a query that forgets it still sees only the rows of
the tenant in `app.tenant_id`, which every session sets per transaction from the
tenant context. Without a context the policy matches nothing (fails closed);
`nullif` covers a pooled connection that once had the setting and now returns ''.

FORCE applies the policy to faclab_owner too: a later data migration runs inside
a tenant (`set_config('app.tenant_id', ..., true)`) or turns it off and on again
in the same migration (`NO FORCE` ... `FORCE`). The platform tables (tenants,
users, login failures, memberships, auth sessions, outbox) have no policy: auth,
provisioning and the relay read them across tenants.

Only on PostgreSQL. A new business table gets the same three statements in its
own migration (`tests/integration/postgres/test_rls.py` checks every table).

Revision ID: 798891c3feea
Revises: 80bfd3a8c63b
Create Date: 2026-10-19 01:24:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "798891c3feea"
down_revision: str | None = "80bfd3a8c63b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"

# The business tables at this revision, frozen
TABLES = (
    "adjustment_items",
    "categories",
    "customer_contacts",
    "customers",
    "inventory_adjustments",
    "locations",
    "lots",
    "movement_lot_items",
    "movements",
    "payments",
    "pos_cash_movements",
    "pos_refund_items",
    "pos_refund_payments",
    "pos_refunds",
    "pos_shifts",
    "products",
    "purchase_order_items",
    "purchase_orders",
    "purchase_receipt_items",
    "purchase_receipts",
    "sale_items",
    "sales",
    "serial_numbers",
    "stock_transfer_items",
    "stock_transfers",
    "stocks",
    "supplier_contacts",
    "supplier_products",
    "suppliers",
    "units_of_measure",
    "warehouses",
)


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    if not _on_postgresql():
        return
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def downgrade() -> None:
    """Downgrade schema."""
    if not _on_postgresql():
        return
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
