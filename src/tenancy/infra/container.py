from src.tenancy.app.commands.provision_tenant import ProvisionTenantCommandHandler
from src.tenancy.infra.mappers import MembershipMapper, TenantMapper
from src.tenancy.infra.repositories import (
    SqlAlchemyMembershipRepository,
    SqlAlchemyTenantRepository,
)

INJECTABLES = [
    TenantMapper,
    MembershipMapper,
    SqlAlchemyTenantRepository,
    SqlAlchemyMembershipRepository,
    ProvisionTenantCommandHandler,
]
