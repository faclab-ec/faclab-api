"""database role privileges

What each role may do with the tables of faclab_owner (S2.4). The roles come
from `python -m src.shared.infra.db_roles` (`make db-roles`), which runs first:

- faclab_app (the API) and faclab_worker (the outbox relay and platform
  lookups) read and write every table, and the default privileges extend that
  to the tables of later migrations. Never TRUNCATE: it ignores row-level
  security.
- outbox_messages: faclab_app only inserts (its INSERT returns the id). Only the
  relay, as faclab_worker, reads and updates the messages of every tenant.
- alembic_version belongs to the migrations alone.

Only on PostgreSQL.

Revision ID: 80bfd3a8c63b
Revises: 3df55a3cc8fb
Create Date: 2026-10-19 01:19:19

"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "80bfd3a8c63b"
down_revision: str | None = "3df55a3cc8fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("faclab_app", "faclab_worker")
GRANTEES = ", ".join(ROLES)
TABLE_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"
SEQUENCE_PRIVILEGES = "USAGE, SELECT"


def _on_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _require_roles() -> None:
    existing = set(
        op.get_bind()
        .execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
            {"roles": list(ROLES)},
        )
        .scalars()
    )
    missing = [role for role in ROLES if role not in existing]
    if missing:
        raise RuntimeError(
            f"Missing database roles {', '.join(missing)}: create them first with "
            "`make db-roles` (python -m src.shared.infra.db_roles)"
        )


def upgrade() -> None:
    """Upgrade schema."""
    if not _on_postgresql():
        return
    _require_roles()
    op.execute(f"GRANT USAGE ON SCHEMA public TO {GRANTEES}")
    op.execute(f"GRANT {TABLE_PRIVILEGES} ON ALL TABLES IN SCHEMA public TO {GRANTEES}")
    op.execute(
        f"GRANT {SEQUENCE_PRIVILEGES} ON ALL SEQUENCES IN SCHEMA public TO {GRANTEES}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE faclab_owner IN SCHEMA public"
        f" GRANT {TABLE_PRIVILEGES} ON TABLES TO {GRANTEES}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE faclab_owner IN SCHEMA public"
        f" GRANT {SEQUENCE_PRIVILEGES} ON SEQUENCES TO {GRANTEES}"
    )
    op.execute(f"REVOKE ALL ON alembic_version FROM {GRANTEES}")
    op.execute("REVOKE ALL ON outbox_messages FROM faclab_app")
    op.execute("GRANT INSERT, SELECT (id) ON outbox_messages TO faclab_app")


def downgrade() -> None:
    """Downgrade schema."""
    if not _on_postgresql():
        return
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE faclab_owner IN SCHEMA public"
        f" REVOKE ALL ON SEQUENCES FROM {GRANTEES}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE faclab_owner IN SCHEMA public"
        f" REVOKE ALL ON TABLES FROM {GRANTEES}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {GRANTEES}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {GRANTEES}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {GRANTEES}")
