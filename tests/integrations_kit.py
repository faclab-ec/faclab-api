"""Runs the commands of the integration clients (S6.2) over a session, with
the real repositories and a fake audit trail, for the unit tests."""

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from src.auth.domain.scopes import Scope
from src.integrations.app.commands.clients import (
    CreateIntegrationClientCommand,
    CreateIntegrationClientCommandHandler,
    RevokeIntegrationClientCommand,
    RevokeIntegrationClientCommandHandler,
    UpdateIntegrationClientCommand,
    UpdateIntegrationClientCommandHandler,
)
from src.integrations.app.commands.secrets import (
    CreateClientSecretCommand,
    CreateClientSecretCommandHandler,
    RevokeClientSecretCommand,
    RevokeClientSecretCommandHandler,
)
from src.integrations.app.commands.token import (
    IssueClientTokenCommand,
    IssueClientTokenCommandHandler,
    TokenDenied,
    TokenGranted,
)
from src.integrations.app.plan import IntegrationPlan, UnlimitedIntegrationPlan
from src.integrations.app.queries.clients import (
    GetIntegrationClientQuery,
    GetIntegrationClientQueryHandler,
    GetIntegrationUsageQuery,
    GetIntegrationUsageQueryHandler,
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
from src.organization.infra.mappers import BranchMapper
from src.organization.infra.repositories import SqlAlchemyBranchRepository
from src.tenancy.infra.mappers import TenantMapper
from src.tenancy.infra.repositories import SqlAlchemyTenantRepository
from tests.audit import FakeAuditTrail
from tests.plans import FakePlanLimits
from tests.tokens import token_service

SANDBOX = IntegrationSettings(environment=IntegrationEnvironment.SANDBOX)


class Kit:
    def __init__(self, session: Session):
        self.session = session
        self.audit = FakeAuditTrail()
        self.limits = FakePlanLimits()
        self.publisher = MagicMock()
        self.clients = SqlAlchemyIntegrationClientRepository(
            session, IntegrationClientMapper()
        )
        self.secrets = SqlAlchemyClientSecretRepository(session, ClientSecretMapper())
        self.usage = SqlAlchemyIntegrationUsageRepository(session)
        self.branches = SqlAlchemyBranchRepository(session, BranchMapper())

    def create(
        self,
        plan: IntegrationPlan | None = None,
        *,
        name: str = "Tienda web",
        scopes: list[Scope] | None = None,
        branch_ids: list[int] | None = None,
        allowed_ips: list[str] | None = None,
    ) -> dict:
        command = CreateIntegrationClientCommand(
            name=name,
            scopes=scopes or [Scope.STOCK_READ],
            branch_ids=branch_ids,
            allowed_ips=allowed_ips,
        )
        return CreateIntegrationClientCommandHandler(
            self.clients,
            self.secrets,
            SqlAlchemyIntegrationDirectory(self.session),
            self.branches,
            plan or UnlimitedIntegrationPlan(),
            self.limits,
            SANDBOX,
            self.audit,
        ).handle(command)

    def update(
        self,
        client_id: int,
        *,
        name: str = "Tienda web",
        scopes: list[Scope] | None = None,
        branch_ids: list[int] | None = None,
        allowed_ips: list[str] | None = None,
    ) -> dict:
        command = UpdateIntegrationClientCommand(
            client_id=client_id,
            name=name,
            scopes=scopes or [Scope.STOCK_READ],
            branch_ids=branch_ids,
            allowed_ips=allowed_ips,
        )
        return UpdateIntegrationClientCommandHandler(
            self.clients,
            self.secrets,
            self.branches,
            UnlimitedIntegrationPlan(),
            self.audit,
        ).handle(command)

    def rotate(self, client_id: int, previous_expires_in_days=None) -> dict:
        return CreateClientSecretCommandHandler(
            self.clients, self.secrets, self.audit
        ).handle(CreateClientSecretCommand(client_id, previous_expires_in_days))

    def revoke_secret(self, client_id: int, secret_id: int) -> dict:
        return RevokeClientSecretCommandHandler(
            self.clients, self.secrets, self.audit
        ).handle(RevokeClientSecretCommand(client_id, secret_id))

    def revoke(self, client_id: int) -> dict:
        return RevokeIntegrationClientCommandHandler(
            self.clients, self.secrets, self.audit, self.publisher, self.session
        ).handle(RevokeIntegrationClientCommand(client_id))

    def token(
        self,
        public_id: str,
        secret: str,
        scope: str | None = None,
        ip: str | None = "203.0.113.7",
        settings: IntegrationSettings = SANDBOX,
    ) -> TokenGranted | TokenDenied:
        return IssueClientTokenCommandHandler(
            self.clients,
            self.secrets,
            self.usage,
            SqlAlchemyTenantRepository(self.session, TenantMapper()),
            token_service(),
            UnlimitedIntegrationPlan(),
            settings,
        ).handle(IssueClientTokenCommand(public_id, secret, scope, ip))

    def detail(self, client_id: int) -> dict:
        return GetIntegrationClientQueryHandler(self.clients, self.secrets).handle(
            GetIntegrationClientQuery(client_id)
        )

    def usage_days(self, client_id: int) -> list[dict]:
        return GetIntegrationUsageQueryHandler(self.clients, self.usage).handle(
            GetIntegrationUsageQuery(client_id)
        )
