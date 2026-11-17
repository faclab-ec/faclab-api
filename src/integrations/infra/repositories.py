from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from wireup import injectable

from src.integrations.app.repositories import (
    ClientSecretRepository,
    IntegrationClientRepository,
    IntegrationDirectory,
    IntegrationUsageRepository,
)
from src.integrations.domain.entities import (
    ClientSecret,
    IntegrationClient,
    IntegrationClientStatus,
)
from src.integrations.infra.mappers import ClientSecretMapper, IntegrationClientMapper
from src.integrations.infra.models import (
    ClientSecretModel,
    IntegrationClientDirectoryModel,
    IntegrationClientModel,
    IntegrationUsageModel,
)
from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository
from src.shared.infra.tenant import tenant_criteria


@injectable(lifetime="scoped", as_type=IntegrationClientRepository)
class SqlAlchemyIntegrationClientRepository(
    SqlAlchemyRepository[IntegrationClient], IntegrationClientRepository
):
    __model__ = IntegrationClientModel

    def __init__(self, session: Session, mapper: IntegrationClientMapper):
        super().__init__(session, mapper)

    def page(
        self,
        status: IntegrationClientStatus | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[IntegrationClient], int]:
        criteria = [] if status is None else [IntegrationClientModel.status == status]
        clients = self.filter(criteria, order_by="id", limit=limit, offset=offset)
        total = self._query(func.count(IntegrationClientModel.id)).filter(*criteria)
        return clients, total.scalar() or 0


@injectable(lifetime="scoped", as_type=ClientSecretRepository)
class SqlAlchemyClientSecretRepository(
    SqlAlchemyRepository[ClientSecret], ClientSecretRepository
):
    __model__ = ClientSecretModel

    def __init__(self, session: Session, mapper: ClientSecretMapper):
        super().__init__(session, mapper)

    def of_clients(self, client_ids: Iterable[int]) -> list[ClientSecret]:
        ids = set(client_ids)
        if not ids:
            return []
        return self.filter([ClientSecretModel.client_id.in_(ids)], order_by="id")


@injectable(lifetime="scoped", as_type=IntegrationDirectory)
class SqlAlchemyIntegrationDirectory(IntegrationDirectory):
    def __init__(self, session: Session):
        self.session = session

    def add(self, public_id: str) -> None:
        tenant_id = require_tenant("registering an integration client").tenant_id
        self.session.add(
            IntegrationClientDirectoryModel(public_id=public_id, tenant_id=tenant_id)
        )
        self.session.flush()


def tenant_of_client(session: Session, public_id: str):
    """The tenant of a client_id, or None. Reads the directory, which has no
    row-level security: it runs before the tenant is known"""
    return session.execute(
        select(IntegrationClientDirectoryModel.tenant_id).where(
            IntegrationClientDirectoryModel.public_id == public_id
        )
    ).scalar_one_or_none()


_COUNTERS = ("token_requests", "token_failures", "requests", "errors")
_USAGE_KEY = ("tenant_id", "client_id", "day")


@injectable(lifetime="scoped", as_type=IntegrationUsageRepository)
class SqlAlchemyIntegrationUsageRepository(IntegrationUsageRepository):
    """One upsert per count: the day's row is created at the first one and
    added to afterwards (`INSERT … ON CONFLICT DO UPDATE`)"""

    def __init__(self, session: Session):
        self.session = session

    def count(
        self,
        client_id: int,
        *,
        at: datetime,
        ip: str | None = None,
        token_requests: int = 0,
        token_failures: int = 0,
        requests: int = 0,
        errors: int = 0,
    ) -> None:
        added = {
            "token_requests": token_requests,
            "token_failures": token_failures,
            "requests": requests,
            "errors": errors,
        }
        values: dict[str, Any] = {
            # A Core insert skips assign_tenant: the tenant goes explicitly
            "tenant_id": require_tenant("counting an integration's usage").tenant_id,
            "client_id": client_id,
            "day": at.date(),
            "last_seen_at": at,
            **added,
        }
        bump: dict[str, Any] = {
            name: getattr(IntegrationUsageModel, name) + added[name]
            for name in _COUNTERS
            if added[name]
        }
        bump["last_seen_at"] = at
        if ip is not None:
            values["last_ip"] = ip
            bump["last_ip"] = ip
        dialect = (
            postgresql
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite
        )
        statement = (
            dialect.insert(IntegrationUsageModel)
            .values(**values)
            .on_conflict_do_update(index_elements=_USAGE_KEY, set_=bump)
        )
        self.session.execute(statement)

    def days(self, client_id: int, from_day: date, to_day: date) -> list[dict]:
        rows = self.session.scalars(
            select(IntegrationUsageModel)
            .where(
                *tenant_criteria(IntegrationUsageModel),
                IntegrationUsageModel.client_id == client_id,
                IntegrationUsageModel.day >= from_day,
                IntegrationUsageModel.day <= to_day,
            )
            .order_by(IntegrationUsageModel.day)
        )
        return [
            {
                "day": row.day,
                "token_requests": row.token_requests,
                "token_failures": row.token_failures,
                "requests": row.requests,
                "errors": row.errors,
                "last_ip": row.last_ip,
                "last_seen_at": row.last_seen_at,
            }
            for row in rows
        ]
