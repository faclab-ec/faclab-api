"""plans and subscriptions

Plans, subscriptions and usage limits (S8.4):

- `plans`: a platform table (no tenant, no row-level security) with the limits
  of each plan (NULL: no limit) and whether it includes the public API; one
  default plan (`uq_plans_default`), the one new tenants get. It starts with
  the default plan `ilimitado` ("Sin límites"), without any limit: decision
  D-5 (the real plans) is still open, the platform adds them with its CLI.
- `subscriptions`: one per tenant (`uq_subscriptions_tenant`), its plan and
  status (`trial`, `active`, `suspended`, `cancelled`). Every existing tenant
  gets an `active` one on the default plan, so nothing changes for them.
- `document_usage`: the electronic documents the SRI authorized to each
  tenant per month (first day of the month in Ecuador). It counts from now on.

`subscriptions` and `document_usage` have row-level security, enabled and
forced after the subscriptions are inserted. The downgrade drops the three
tables.

Revision ID: a22a34717c3e
Revises: e5b8c1d4a7f2
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a22a34717c3e"
down_revision: str | None = "e5b8c1d4a7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
LIMITS = (
    "max_branches",
    "max_terminals",
    "max_users",
    "max_integration_clients",
    "max_webhook_endpoints",
    "max_monthly_documents",
)


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _isolate(table: str) -> None:
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def upgrade() -> None:
    """Upgrade schema."""
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        *(sa.Column(limit, sa.Integer(), nullable=True) for limit in LIMITS),
        sa.Column("public_api", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(
        "uq_plans_default",
        "plans",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(), nullable=True),
        sa.Column("status_changed_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant"),
    )
    op.create_index(op.f("ix_subscriptions_tenant_id"), "subscriptions", ["tenant_id"])
    op.create_index(op.f("ix_subscriptions_plan_id"), "subscriptions", ["plan_id"])

    op.create_table(
        "document_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("invoices", sa.Integer(), nullable=False),
        sa.Column("credit_notes", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "period", name="uq_document_usage_tenant_period"
        ),
    )
    op.create_index(
        op.f("ix_document_usage_tenant_id"), "document_usage", ["tenant_id"]
    )

    # The default plan, without limits, and every tenant on it
    op.bulk_insert(
        plans,
        [
            {
                "code": "ilimitado",
                "name": "Sin límites",
                **dict.fromkeys(LIMITS),
                "public_api": True,
                "is_default": True,
                "is_active": True,
                "created_at": sa.func.current_timestamp(),
                "updated_at": sa.func.current_timestamp(),
            }
        ],
        multiinsert=False,
    )
    op.execute(
        """
        INSERT INTO subscriptions (
            tenant_id, plan_id, status, status_changed_at, status_changed_by,
            created_at, updated_at
        )
        SELECT t.id, p.id, 'active', CURRENT_TIMESTAMP, 'migration',
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM tenants t CROSS JOIN plans p
        WHERE p.code = 'ilimitado'
        """
    )
    _isolate("subscriptions")
    _isolate("document_usage")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_document_usage_tenant_id"), table_name="document_usage")
    op.drop_table("document_usage")
    op.drop_index(op.f("ix_subscriptions_plan_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_tenant_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("uq_plans_default", table_name="plans")
    op.drop_table("plans")
