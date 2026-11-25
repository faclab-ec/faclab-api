"""The data side of a company's offboarding (S8.7), as faclab_worker.

Runs in the company's context but the worker has no row-level security, so every
statement filters by tenant itself. Tables come from `Base.metadata`.

What is deleted when anonymizing is a list (`PURGE_ON_ANONYMIZE`): the
technical and access data tax law has no use for. What is anonymized is found by
column name (the authors' names: `*_by`, `cashier_name`...; free notes) plus the
personal data of customers and suppliers, whose tax identification stays. What is
left is the company's accounting: sales, purchases, payments, accounts, stock,
movements, catalog, the audit log (actors anonymized) and the tenant itself.

`audit_log` and the shift closings are append-only for every role but the owner:
the two SQL functions of migration e6b2a9c4d715 touch them (PostgreSQL only).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, Table, cast, delete, func, literal, select, text, update
from sqlalchemy.orm import Session
from wireup import injectable

from src.data_protection.app.offboarding import TenantDataCleaner
from src.shared.infra.database import Base

# Children before parents: deleted in the reverse of the metadata's order
PURGE_ON_ANONYMIZE = frozenset(
    {
        "auth_sessions",
        "idempotency_keys",
        "outbox_messages",
        "dead_letters",
        "integration_client_directory",
        "integration_client_usage",
        "integration_client_secrets",
        "integration_clients",
        "webhook_stock_changes",
        "webhook_deliveries",
        "webhook_messages",
        "webhook_endpoints",
        "import_job_rows",
        "import_jobs",
        "export_jobs",
        "user_branch_access",
        "memberships",
        "customer_contacts",
        "supplier_contacts",
    }
)
# Written by the append-only functions, not by statements
APPEND_ONLY = frozenset({"audit_log", "pos_shift_closings", "pos_shift_closing_lines"})
# Platform entries: the operator's name is not the company's personal data
SKIP_ANONYMIZING = frozenset({"subscriptions"})
FREE_TEXT = frozenset({"notes", "park_reason"})
ANONYMOUS_USER = "Usuario anonimizado"
ANONYMOUS_CASHIER = "Cajero anonimizado"

# Personal data of the people the company sells to and buys from; the tax
# identification and type stay (they identify the buyer on a retained invoice)
PARTNER_COLUMNS = {
    "customers": ("email", "phone", "address", "city", "state", "country"),
    "suppliers": ("email", "phone", "address", "city", "country", "notes"),
}
PARTNER_NAME = {
    "customers": "Cliente anonimizado ",
    "suppliers": "Proveedor anonimizado ",
}


def _author_columns(table: Table) -> list[str]:
    """Columns that hold the name of whoever did something"""
    return [
        column.name
        for column in table.columns
        if isinstance(column.type, String)
        and (
            column.name.endswith("_by")
            or column.name.endswith("_by_name")
            or column.name in ("cashier_name", "user_name")
        )
    ]


def _purge_tables() -> list[Table]:
    return [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if table.name in PURGE_ON_ANONYMIZE
    ]


def _anonymizable_tables() -> list[Table]:
    return [
        table
        for table in Base.metadata.sorted_tables
        if "tenant_id" in table.c
        and table.name not in PURGE_ON_ANONYMIZE
        and table.name not in APPEND_ONLY
        and table.name not in SKIP_ANONYMIZING
    ]


def _free_text_columns(table: Table) -> list[str]:
    return [
        column.name
        for column in table.columns
        if column.name in FREE_TEXT and column.nullable
    ]


@injectable(lifetime="scoped", as_type=TenantDataCleaner)
class SqlAlchemyTenantDataCleaner(TenantDataCleaner):
    def __init__(self, session: Session):
        self.session = session

    # Reads

    def last_fiscal_activity(self, tenant_id: UUID) -> datetime | None:
        sales = Base.metadata.tables["sales"]
        return self.session.scalar(
            select(func.max(sales.c.created_at)).where(sales.c.tenant_id == tenant_id)
        )

    def pending_outbox(self, tenant_id: UUID) -> int:
        outbox = Base.metadata.tables["outbox_messages"]
        return self._count(outbox, outbox.c.status == "pending", tenant_id)

    def _count(self, table: Table, condition, tenant_id: UUID) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == tenant_id, condition)
            )
            or 0
        )

    def _rows(self, table: Table, tenant_id: UUID) -> int:
        return self._count(table, literal(True), tenant_id)

    def plan(self, tenant_id: UUID) -> dict[str, dict[str, int]]:
        purge = {t.name: self._rows(t, tenant_id) for t in _purge_tables()}
        anonymize = {"users": len(self._orphan_users(tenant_id))}
        for name in PARTNER_COLUMNS:
            anonymize[name] = self._rows(Base.metadata.tables[name], tenant_id)
        retain: dict[str, int] = {}
        for table in _anonymizable_tables():
            rows = self._rows(table, tenant_id)
            retain[table.name] = rows
            if table.name not in PARTNER_COLUMNS and (
                _author_columns(table) or _free_text_columns(table)
            ):
                anonymize[table.name] = rows
        for name in sorted(APPEND_ONLY):
            retain[name] = self._rows(Base.metadata.tables[name], tenant_id)
        anonymize["audit_log"] = retain["audit_log"]
        anonymize["pos_shift_closings"] = retain["pos_shift_closings"]
        return {
            "purge": {k: v for k, v in purge.items() if v},
            "anonymize": {k: v for k, v in anonymize.items() if v},
            "retain": {k: v for k, v in retain.items() if v},
        }

    # Step 2

    def _orphan_users(self, tenant_id: UUID) -> list[int]:
        """The users that belong to this company alone: global identities with
        no other membership and that aren't platform operators"""
        memberships = Base.metadata.tables["memberships"]
        operators = Base.metadata.tables["platform_operators"]
        here = select(memberships.c.user_id).where(memberships.c.tenant_id == tenant_id)
        elsewhere = select(memberships.c.user_id).where(
            memberships.c.tenant_id != tenant_id
        )
        users = Base.metadata.tables["users"]
        return list(
            self.session.scalars(
                select(users.c.id)
                .where(users.c.id.in_(here))
                .where(users.c.id.not_in(elsewhere))
                .where(users.c.id.not_in(select(operators.c.user_id)))
            )
        )

    def anonymize(self, tenant_id: UUID) -> dict[str, dict[str, int]]:
        anonymized: dict[str, int] = {}
        deleted: dict[str, int] = {}
        users = Base.metadata.tables["users"]
        orphans = self._orphan_users(tenant_id)
        usernames = list(
            self.session.scalars(
                select(users.c.username).where(users.c.id.in_(orphans))
            )
        )

        self._anonymize_partners(tenant_id, anonymized)
        for table in _anonymizable_tables():
            values: dict = dict.fromkeys(_author_columns(table), ANONYMOUS_USER)
            # An author's name that can't be null is a cashier's
            for column in table.columns:
                if column.name in values and not column.nullable:
                    values[column.name] = ANONYMOUS_CASHIER
            values.update(dict.fromkeys(_free_text_columns(table)))
            if not values or table.name in PARTNER_COLUMNS:
                continue
            result = self.session.execute(
                update(table).where(table.c.tenant_id == tenant_id).values(**values)
            )
            if result.rowcount:
                anonymized[table.name] = result.rowcount
        self._nullify_clients_of_sales(tenant_id)
        if self._is_postgresql():
            anonymized["audit_log_and_closings"] = (
                self.session.scalar(
                    text("SELECT faclab_anonymize_append_only(:tenant)"),
                    {"tenant": tenant_id},
                )
                or 0
            )
        for table in _purge_tables():
            deleted[table.name] = self._delete(table, tenant_id)
        self._delete_rate_limits(tenant_id)
        anonymized["users"] = self._anonymize_users(orphans, usernames)
        return {
            "purge": {k: v for k, v in deleted.items() if v},
            "anonymize": {k: v for k, v in anonymized.items() if v},
        }

    def _anonymize_partners(self, tenant_id: UUID, anonymized: dict[str, int]) -> None:
        for name, columns in PARTNER_COLUMNS.items():
            table = Base.metadata.tables[name]
            values = dict.fromkeys(columns)
            values["name"] = literal(PARTNER_NAME[name]) + cast(table.c.id, String)
            result = self.session.execute(
                update(table).where(table.c.tenant_id == tenant_id).values(**values)
            )
            anonymized[name] = result.rowcount

    def _nullify_clients_of_sales(self, tenant_id: UUID) -> None:
        """Sales keep their channel and reference; the client they came
        through is deleted with the integrations"""
        sales = Base.metadata.tables["sales"]
        self.session.execute(
            update(sales)
            .where(sales.c.tenant_id == tenant_id)
            .where(sales.c.integration_client_id.is_not(None))
            .values(integration_client_id=None)
        )

    def _anonymize_users(self, user_ids: list[int], usernames: list[str]) -> int:
        """The people of this company only: their identity becomes a shell no
        one can sign in with. Their failed logins go too"""
        if not user_ids:
            return 0
        users = Base.metadata.tables["users"]
        failures = Base.metadata.tables["login_failures"]
        if usernames:
            self.session.execute(
                delete(failures).where(failures.c.username.in_(usernames))
            )
        result = self.session.execute(
            update(users)
            .where(users.c.id.in_(user_ids))
            .values(
                username=literal("anonimizado-") + cast(users.c.id, String),
                email=literal("anonimizado-")
                + cast(users.c.id, String)
                + literal("@invalid.example"),
                full_name=None,
                password_hash="!",
                is_active=False,
            )
        )
        return result.rowcount

    def _delete(self, table: Table, tenant_id: UUID) -> int:
        return self.session.execute(
            delete(table).where(table.c.tenant_id == tenant_id)
        ).rowcount

    def _delete_rate_limits(self, tenant_id: UUID) -> None:
        limits = Base.metadata.tables["api_rate_limits"]
        self.session.execute(delete(limits).where(limits.c.key.like(f"%:{tenant_id}%")))

    def _is_postgresql(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    # Step 3

    def purge(self, tenant_id: UUID) -> dict[str, int]:
        deleted: dict[str, int] = {}
        if self._is_postgresql():
            deleted["audit_log_and_closings"] = (
                self.session.scalar(
                    text("SELECT faclab_purge_append_only(:tenant)"),
                    {"tenant": tenant_id},
                )
                or 0
            )
        self._nullify_clients_of_sales(tenant_id)
        for table in reversed(Base.metadata.sorted_tables):
            if "tenant_id" not in table.c or table.name in APPEND_ONLY:
                continue
            if table.name in ("users", "tenants"):
                continue
            deleted[table.name] = self._delete(table, tenant_id)
        self._delete_rate_limits(tenant_id)
        tenants = Base.metadata.tables["tenants"]
        deleted["tenants"] = self.session.execute(
            delete(tenants).where(tenants.c.id == tenant_id)
        ).rowcount
        return {k: v for k, v in deleted.items() if v}
