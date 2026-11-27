from src.platform_console.app.commands.login import PlatformLoginCommandHandler
from src.platform_console.app.commands.tenants import (
    ActivateTenantCommandHandler,
    ChangeTenantSubscriptionCommandHandler,
    SuspendTenantCommandHandler,
)
from src.platform_console.app.queries.tenants import (
    GetTenantQueryHandler,
    ListTenantsQueryHandler,
)
from src.platform_console.infra.console import PlatformConsole
from src.platform_console.infra.mappers import PlatformOperatorMapper
from src.platform_console.infra.operators import RepositoryPlatformOperators
from src.platform_console.infra.repositories import SqlAlchemyPlatformOperatorRepository

INJECTABLES = [
    PlatformOperatorMapper,
    SqlAlchemyPlatformOperatorRepository,
    RepositoryPlatformOperators,
    PlatformConsole,
    PlatformLoginCommandHandler,
    SuspendTenantCommandHandler,
    ActivateTenantCommandHandler,
    ChangeTenantSubscriptionCommandHandler,
    ListTenantsQueryHandler,
    GetTenantQueryHandler,
]
