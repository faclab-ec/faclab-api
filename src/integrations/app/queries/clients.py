from dataclasses import dataclass
from datetime import date, datetime, timedelta

from wireup import injectable

from src.integrations.app.commands.clients import get_client
from src.integrations.app.repositories import (
    ClientSecretRepository,
    IntegrationClientRepository,
    IntegrationUsageRepository,
)
from src.integrations.app.views import describe_client
from src.integrations.domain.entities import IntegrationClientStatus
from src.shared.app.queries import Query, QueryHandler

# The usage shown without dates: the last 30 days
USAGE_DEFAULT_DAYS = 30


@dataclass
class ListIntegrationClientsQuery(Query):
    status: IntegrationClientStatus | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class ListIntegrationClientsQueryHandler(
    QueryHandler[ListIntegrationClientsQuery, dict]
):
    def __init__(
        self, clients: IntegrationClientRepository, secrets: ClientSecretRepository
    ):
        self.clients = clients
        self.secrets = secrets

    def _handle(self, query: ListIntegrationClientsQuery) -> dict:
        clients, total = self.clients.page(query.status, query.limit, query.offset)
        secrets = self.secrets.of_clients(client.require_id() for client in clients)
        now = datetime.now()
        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": [
                describe_client(
                    client,
                    [s for s in secrets if s.client_id == client.id],
                    now,
                )
                for client in clients
            ],
        }


@dataclass
class GetIntegrationClientQuery(Query):
    client_id: int


@injectable(lifetime="scoped")
class GetIntegrationClientQueryHandler(QueryHandler[GetIntegrationClientQuery, dict]):
    def __init__(
        self, clients: IntegrationClientRepository, secrets: ClientSecretRepository
    ):
        self.clients = clients
        self.secrets = secrets

    def _handle(self, query: GetIntegrationClientQuery) -> dict:
        client = get_client(self.clients, query.client_id)
        secrets = self.secrets.of_clients([client.require_id()])
        return describe_client(client, secrets, datetime.now())


@dataclass
class GetIntegrationUsageQuery(Query):
    client_id: int
    from_date: date | None = None
    to_date: date | None = None


@injectable(lifetime="scoped")
class GetIntegrationUsageQueryHandler(
    QueryHandler[GetIntegrationUsageQuery, list[dict]]
):
    """Tokens obtained and refused, requests and errors per day"""

    def __init__(
        self, clients: IntegrationClientRepository, usage: IntegrationUsageRepository
    ):
        self.clients = clients
        self.usage = usage

    def _handle(self, query: GetIntegrationUsageQuery) -> list[dict]:
        client = get_client(self.clients, query.client_id)
        to_date = query.to_date or date.today()
        from_date = query.from_date or to_date - timedelta(days=USAGE_DEFAULT_DAYS - 1)
        return self.usage.days(client.require_id(), from_date, to_date)
