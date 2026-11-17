from dataclasses import dataclass
from datetime import datetime, timedelta

from wireup import injectable

from src.integrations.app.commands.clients import get_client
from src.integrations.app.repositories import (
    ClientSecretRepository,
    IntegrationClientRepository,
)
from src.integrations.app.views import describe_secret
from src.integrations.domain.credentials import new_secret
from src.integrations.domain.entities import MAX_ACTIVE_SECRETS, ClientSecret
from src.integrations.domain.exceptions import (
    IntegrationSecretLimitReachedError,
    IntegrationSecretRevokedError,
)
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateClientSecretCommand(Command):
    client_id: int
    # The active secrets stop working in this many days (0: now); None keeps
    # them until they are revoked
    previous_expires_in_days: int | None = None


@injectable(lifetime="scoped")
class CreateClientSecretCommandHandler(CommandHandler[CreateClientSecretCommand, dict]):
    """Rotation: a new secret, shown once in `client_secret`, next to the
    current one (at most two active). The integration switches to it and then
    the old one is revoked, or expires on its own."""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        audit: AuditTrail,
    ):
        self.clients = clients
        self.secrets = secrets
        self.audit = audit

    def _handle(self, command: CreateClientSecretCommand) -> dict:
        # Locked: two rotations at once can't leave three active secrets
        client = get_client(self.clients, command.client_id, for_update=True)
        client.ensure_active()
        now = datetime.now()
        active = [
            secret
            for secret in self.secrets.of_clients([client.require_id()])
            if secret.is_active(now)
        ]
        expires_at = None
        if command.previous_expires_in_days is not None:
            expires_at = now + timedelta(days=command.previous_expires_in_days)
            for secret in active:
                secret.expire_at(expires_at)
                self.secrets.update(secret)
            active = [secret for secret in active if secret.is_active(now)]
        if len(active) >= MAX_ACTIVE_SECRETS:
            raise IntegrationSecretLimitReachedError(MAX_ACTIVE_SECRETS)

        plain = new_secret()
        secret = self.secrets.create(
            ClientSecret.for_client(client.require_id(), plain)
        )
        self.audit.record(
            AuditAction.INTEGRATION_SECRET_CREATED,
            client.require_id(),
            after={
                "secret_id": secret.require_id(),
                "previous_expire_at": expires_at,
            },
        )
        return {**describe_secret(secret, now), "client_secret": plain}


@dataclass
class RevokeClientSecretCommand(Command):
    client_id: int
    secret_id: int


@injectable(lifetime="scoped")
class RevokeClientSecretCommandHandler(CommandHandler[RevokeClientSecretCommand, dict]):
    """It gets no more tokens, and the ones obtained with it stop working
    within the status cache"""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        audit: AuditTrail,
    ):
        self.clients = clients
        self.secrets = secrets
        self.audit = audit

    def _handle(self, command: RevokeClientSecretCommand) -> dict:
        client = get_client(self.clients, command.client_id, for_update=True)
        secret = self.secrets.first(id=command.secret_id, client_id=client.require_id())
        if secret is None:
            raise NotFoundError(f"Secret {command.secret_id} not found")
        if secret.revoked_at is not None:
            raise IntegrationSecretRevokedError()
        now = datetime.now()
        secret.revoke(now)
        secret = self.secrets.update(secret)
        self.audit.record(
            AuditAction.INTEGRATION_SECRET_REVOKED,
            client.require_id(),
            after={"secret_id": secret.require_id()},
        )
        return describe_secret(secret, now)
