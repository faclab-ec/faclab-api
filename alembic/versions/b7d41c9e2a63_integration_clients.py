"""integration clients

Integration credentials with OAuth 2.0 client credentials (S6.2, G-72):

- `integration_clients`: a system of the tenant that calls the API, with its
  public client_id (fl_live_… / fl_test_…), name, environment, status, scopes
  and the branches and networks it is limited to (JSON lists).
- `integration_client_secrets`: its secrets, only their SHA-256 and the first
  characters; up to two active at a time (rotation).
- `integration_client_usage`: counters per client and day (tokens obtained and
  refused, requests, errors, the last source address).
- `integration_client_directory`: client_id -> tenant, without row-level
  security like `auth_sessions`: the token endpoint reads it before it knows
  the tenant. Every other table has row-level security, enabled and forced.
- `audit_log.actor_integration_id`: the client that did an audited operation
  with its token (the user is null then).

The downgrade drops them: the clients and their usage are lost, and every
token they hold stops working.

Revision ID: b7d41c9e2a63
Revises: 882414a85890
Create Date: 2026-11-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d41c9e2a63"
down_revision: str | None = "882414a85890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
INDEXES = {
    "integration_clients": ("tenant_id",),
    "integration_client_secrets": ("tenant_id", "client_id"),
    "integration_client_usage": ("tenant_id", "client_id"),
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


def _client_column() -> sa.Column:
    return sa.Column(
        "client_id",
        sa.Integer(),
        sa.ForeignKey("integration_clients.id", ondelete="RESTRICT"),
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
        "integration_clients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        sa.Column("public_id", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("branch_ids", sa.JSON(), nullable=True),
        sa.Column("allowed_ips", sa.JSON(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "public_id", name="uq_integration_clients_tenant_public_id"
        ),
    )
    _indexes_and_isolation("integration_clients")

    op.create_table(
        "integration_client_secrets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        _client_column(),
        sa.Column("prefix", sa.String(length=8), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes_and_isolation("integration_client_secrets")

    op.create_table(
        "integration_client_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        _tenant_column(),
        _client_column(),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("token_requests", sa.Integer(), nullable=False),
        sa.Column("token_failures", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("last_ip", sa.String(length=45), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "client_id",
            "day",
            name="uq_integration_client_usage_tenant_client_day",
        ),
    )
    _indexes_and_isolation("integration_client_usage")

    # Without row-level security: read before the tenant is known
    op.create_table(
        "integration_client_directory",
        sa.Column("public_id", sa.String(length=24), nullable=False),
        _tenant_column(),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("public_id"),
    )
    op.create_index(
        op.f("ix_integration_client_directory_tenant_id"),
        "integration_client_directory",
        ["tenant_id"],
    )

    op.add_column(
        "audit_log", sa.Column("actor_integration_id", sa.Integer(), nullable=True)
    )
    op.create_index(
        op.f("ix_audit_log_actor_integration_id"),
        "audit_log",
        ["actor_integration_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_audit_log_actor_integration_id"), table_name="audit_log")
    op.drop_column("audit_log", "actor_integration_id")
    op.drop_index(
        op.f("ix_integration_client_directory_tenant_id"),
        table_name="integration_client_directory",
    )
    op.drop_table("integration_client_directory")
    _drop("integration_client_usage")
    _drop("integration_client_secrets")
    _drop("integration_clients")
