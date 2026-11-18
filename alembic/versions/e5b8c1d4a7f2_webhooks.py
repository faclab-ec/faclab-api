"""webhooks

Signed webhooks (S6.4, G-72, ADR-0009):

- `webhook_endpoints`: an HTTPS URL of the tenant with the events it receives,
  optionally of an integration client (composite key: one of the tenant), its
  secret encrypted with the environment's master key (and the previous one
  during a rotation), its status and since when it fails.
- `webhook_messages`: an event as it is sent (the whole body, the same in each
  attempt), with the integration client whose request caused it.
- `webhook_deliveries`: a message on its way to one endpoint, with its
  attempts, the next one and the lease of the worker sending it.
- `webhook_stock_changes`: the stock rows that changed, which the worker groups
  as `stock.changed` every 30 s.

Every table has row-level security, enabled and forced. The downgrade drops
them: the endpoints and their history are lost.

Revision ID: e5b8c1d4a7f2
Revises: c4e9a7d2f1b8
Create Date: 2026-11-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b8c1d4a7f2"
down_revision: str | None = "c4e9a7d2f1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
INDEXES = {
    "webhook_endpoints": ("tenant_id", "integration_client_id"),
    "webhook_messages": ("tenant_id", "created_at"),
    "webhook_deliveries": ("tenant_id", "message_id"),
    "webhook_stock_changes": ("tenant_id",),
}


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _indexes_and_isolation(table: str) -> None:
    for column in INDEXES[table]:
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column])
    if _on_postgresql():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({TENANT}) WITH CHECK ({TENANT})"
        )


def _drop(table: str) -> None:
    for column in reversed(INDEXES[table]):
        op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("event_types", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("disabled_reason", sa.String(length=32), nullable=True),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("integration_client_id", sa.Integer(), nullable=True),
        sa.Column("exclude_own_changes", sa.Boolean(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=16), nullable=False),
        sa.Column("previous_secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("previous_secret_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("failing_since", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_webhook_endpoints_tenant_id_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "integration_client_id"],
            ["integration_clients.tenant_id", "integration_clients.id"],
            name="fk_webhook_endpoints_integration_client_tenant",
            ondelete="RESTRICT",
        ),
    )
    _indexes_and_isolation("webhook_endpoints")

    op.create_table(
        "webhook_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("public_id", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("origin_integration_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "public_id", name="uq_webhook_messages_tenant_public_id"
        ),
    )
    _indexes_and_isolation("webhook_messages")

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("webhook_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "endpoint_id",
            sa.Integer(),
            sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("retried_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes_and_isolation("webhook_deliveries")
    op.create_index(
        "ix_webhook_deliveries_pending",
        "webhook_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_webhook_deliveries_endpoint_created",
        "webhook_deliveries",
        ["endpoint_id", "created_at"],
    )
    op.create_index(
        "ix_webhook_deliveries_locked",
        "webhook_deliveries",
        ["locked_until"],
        postgresql_where=sa.text("locked_until IS NOT NULL"),
        sqlite_where=sa.text("locked_until IS NOT NULL"),
    )

    op.create_table(
        "webhook_stock_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("origin_integration_id", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes_and_isolation("webhook_stock_changes")


def downgrade() -> None:
    """Downgrade schema."""
    _drop("webhook_stock_changes")
    op.drop_index("ix_webhook_deliveries_locked", table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_endpoint_created", table_name="webhook_deliveries"
    )
    op.drop_index("ix_webhook_deliveries_pending", table_name="webhook_deliveries")
    _drop("webhook_deliveries")
    _drop("webhook_messages")
    _drop("webhook_endpoints")
