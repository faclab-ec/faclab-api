from wireup import injectable

from config import config
from src.integrations.app.commands.clients import (
    CreateIntegrationClientCommandHandler,
    RevokeIntegrationClientCommandHandler,
    UpdateIntegrationClientCommandHandler,
)
from src.integrations.app.commands.secrets import (
    CreateClientSecretCommandHandler,
    RevokeClientSecretCommandHandler,
)
from src.integrations.app.commands.token import IssueClientTokenCommandHandler
from src.integrations.app.plan import UnlimitedIntegrationPlan
from src.integrations.app.queries.clients import (
    GetIntegrationClientQueryHandler,
    GetIntegrationUsageQueryHandler,
    ListIntegrationClientsQueryHandler,
)
from src.integrations.app.settings import IntegrationSettings
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.infra.mappers import ClientSecretMapper, IntegrationClientMapper
from src.integrations.infra.repositories import (
    SqlAlchemyClientSecretRepository,
    SqlAlchemyIntegrationClientRepository,
    SqlAlchemyIntegrationDirectory,
    SqlAlchemyIntegrationUsageRepository,
)


@injectable(lifetime="singleton")
def integration_settings() -> IntegrationSettings:
    return IntegrationSettings(
        environment=IntegrationEnvironment(config.INTEGRATION_ENVIRONMENT)
    )


INJECTABLES = [
    integration_settings,
    UnlimitedIntegrationPlan,
    IntegrationClientMapper,
    ClientSecretMapper,
    SqlAlchemyIntegrationClientRepository,
    SqlAlchemyClientSecretRepository,
    SqlAlchemyIntegrationDirectory,
    SqlAlchemyIntegrationUsageRepository,
    CreateIntegrationClientCommandHandler,
    UpdateIntegrationClientCommandHandler,
    RevokeIntegrationClientCommandHandler,
    CreateClientSecretCommandHandler,
    RevokeClientSecretCommandHandler,
    IssueClientTokenCommandHandler,
    ListIntegrationClientsQueryHandler,
    GetIntegrationClientQueryHandler,
    GetIntegrationUsageQueryHandler,
]
