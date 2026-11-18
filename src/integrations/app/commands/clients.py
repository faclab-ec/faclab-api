from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.domain.scopes import Scope
from src.integrations.app.plan import IntegrationPlan
from src.integrations.app.repositories import (
    ClientSecretRepository,
    IntegrationClientRepository,
    IntegrationDirectory,
)
from src.integrations.app.settings import IntegrationSettings
from src.integrations.app.views import describe_client
from src.integrations.domain.credentials import new_secret
from src.integrations.domain.entities import ClientSecret, IntegrationClient
from src.integrations.domain.events import IntegrationClientRevoked
from src.integrations.domain.exceptions import (
    IntegrationBranchNotFoundError,
    ScopeNotInPlanError,
)
from src.organization.app.repositories import BranchRepository
from src.shared.app.audit import AuditAction, AuditTrail, changed, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError

# What the audit log keeps of a client: never a secret nor its hash
AUDITED_FIELDS = ("name", "scopes", "branch_ids", "allowed_ips")


@dataclass
class CreateIntegrationClientCommand(Command):
    name: str
    scopes: list[Scope] = field(default_factory=list)
    branch_ids: list[int] | None = None
    allowed_ips: list[str] | None = None


@injectable(lifetime="scoped")
class CreateIntegrationClientCommandHandler(
    CommandHandler[CreateIntegrationClientCommand, dict]
):
    """A client of the deployment's environment with its first secret, which
    the result carries in `client_secret`: the only time it is shown"""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        directory: IntegrationDirectory,
        branches: BranchRepository,
        plan: IntegrationPlan,
        settings: IntegrationSettings,
        audit: AuditTrail,
    ):
        self.clients = clients
        self.secrets = secrets
        self.directory = directory
        self.branches = branches
        self.plan = plan
        self.settings = settings
        self.audit = audit

    def _handle(self, command: CreateIntegrationClientCommand) -> dict:
        scopes = frozenset(command.scopes)
        ensure_in_plan(scopes, self.plan)
        ensure_branches(self.branches, command.branch_ids)
        client = IntegrationClient.new(
            self.settings.environment,
            command.name,
            scopes,
            command.branch_ids,
            command.allowed_ips,
        )
        self.directory.add(client.public_id)
        client = self.clients.create(client)
        plain = new_secret()
        secret = self.secrets.create(
            ClientSecret.for_client(client.require_id(), plain)
        )
        self.audit.record(
            AuditAction.INTEGRATION_CREATED,
            client.require_id(),
            after={
                "client_id": client.public_id,
                "environment": client.environment,
                **snapshot(client, *AUDITED_FIELDS),
                "secret_id": secret.require_id(),
            },
        )
        return {
            **describe_client(client, [secret], datetime.now()),
            "client_secret": plain,
        }


@dataclass
class UpdateIntegrationClientCommand(Command):
    client_id: int
    name: str
    scopes: list[Scope] = field(default_factory=list)
    branch_ids: list[int] | None = None
    allowed_ips: list[str] | None = None


@injectable(lifetime="scoped")
class UpdateIntegrationClientCommandHandler(
    CommandHandler[UpdateIntegrationClientCommand, dict]
):
    """Its name, scopes, branches and addresses. The tokens already issued
    narrow to them within the status cache (INTEGRATION_STATUS_CACHE_SECONDS)"""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        branches: BranchRepository,
        plan: IntegrationPlan,
        audit: AuditTrail,
    ):
        self.clients = clients
        self.secrets = secrets
        self.branches = branches
        self.plan = plan
        self.audit = audit

    def _handle(self, command: UpdateIntegrationClientCommand) -> dict:
        client = get_client(self.clients, command.client_id, for_update=True)
        previous = snapshot(client, *AUDITED_FIELDS)
        scopes = frozenset(command.scopes)
        ensure_in_plan(scopes, self.plan)
        ensure_branches(self.branches, command.branch_ids)
        client.configure(command.name, scopes, command.branch_ids, command.allowed_ips)
        client = self.clients.update(client)
        before, after = changed(previous, snapshot(client, *AUDITED_FIELDS))
        if after:
            self.audit.record(
                AuditAction.INTEGRATION_UPDATED,
                client.require_id(),
                before=before,
                after=after,
            )
        return describe_client(
            client, self.secrets.of_clients([client.require_id()]), datetime.now()
        )


@dataclass
class RevokeIntegrationClientCommand(Command):
    client_id: int


@injectable(lifetime="scoped")
class RevokeIntegrationClientCommandHandler(
    CommandHandler[RevokeIntegrationClientCommand, dict]
):
    """For good: its secrets are revoked, it gets no more tokens and the ones
    it has stop working within the status cache"""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        audit: AuditTrail,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.clients = clients
        self.secrets = secrets
        self.audit = audit
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: RevokeIntegrationClientCommand) -> dict:
        client = get_client(self.clients, command.client_id, for_update=True)
        now = datetime.now()
        client.revoke(now)
        client = self.clients.update(client)
        secrets = self.secrets.of_clients([client.require_id()])
        for secret in secrets:
            if secret.revoked_at is None:
                secret.revoke(now)
                self.secrets.update(secret)
        self.audit.record(
            AuditAction.INTEGRATION_REVOKED,
            client.require_id(),
            before={"status": "ACTIVE"},
            after={"status": client.status},
        )
        self.event_publisher.publish(
            IntegrationClientRevoked(
                aggregate_id=client.require_id(), client_id=client.require_id()
            ),
            session=self.session,
        )
        return describe_client(client, secrets, now)


def get_client(
    clients: IntegrationClientRepository, client_id: int, for_update: bool = False
) -> IntegrationClient:
    client = (
        clients.first_for_update(id=client_id)
        if for_update
        else clients.get_by_id(client_id)
    )
    if client is None:
        raise NotFoundError(f"Integration client {client_id} not found")
    return client


def ensure_in_plan(scopes: frozenset[Scope], plan: IntegrationPlan) -> None:
    outside = sorted(scope.value for scope in scopes - plan.allowed_scopes())
    if outside:
        raise ScopeNotInPlanError(outside)


def ensure_branches(
    branches: BranchRepository, branch_ids: Iterable[int] | None
) -> None:
    """Every branch is the tenant's: the column has no foreign key"""
    wanted = set(branch_ids or ())
    if not wanted:
        return
    found = {branch.require_id() for branch in branches.get_by_ids(wanted)}
    missing = sorted(wanted - found)
    if missing:
        raise IntegrationBranchNotFoundError(missing)
