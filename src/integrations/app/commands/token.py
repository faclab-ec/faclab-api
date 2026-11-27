from dataclasses import dataclass
from datetime import datetime

import structlog
from wireup import injectable

from src.auth.app.services.token_service import TokenService
from src.auth.domain.scopes import Scope, format_scopes, parse_scopes
from src.integrations.app.plan import IntegrationPlan
from src.integrations.app.repositories import (
    ClientSecretRepository,
    IntegrationClientRepository,
    IntegrationUsageRepository,
)
from src.integrations.app.settings import IntegrationSettings
from src.integrations.domain.credentials import decoy_check
from src.integrations.domain.entities import ClientSecret, IntegrationClient
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.tenant import require_tenant
from src.tenancy.app.repositories import TenantRepository
from src.tenancy.domain.entities import TenantStatus

logger = structlog.get_logger(__name__)

INVALID_CLIENT = "invalid_client"
INVALID_SCOPE = "invalid_scope"


@dataclass
class IssueClientTokenCommand(Command):
    """Runs in the tenant of the client_id (the token endpoint finds it first).
    The secret is never logged: the handler only logs the command's name"""

    public_id: str
    client_secret: str
    # OAuth's `scope`, space separated; None: every scope the client has
    scope: str | None = None
    ip: str | None = None


@dataclass(frozen=True)
class TokenGranted:
    access_token: str
    expires_in: int
    scope: str


@dataclass(frozen=True)
class TokenDenied:
    """An OAuth error (RFC 6749 §5.2): `error` goes to the client and `reason`
    only to the log, so a caller can't tell a wrong secret from a revoked
    client"""

    error: str
    reason: str
    description: str = "client authentication failed"


@injectable(lifetime="scoped")
class IssueClientTokenCommandHandler(
    CommandHandler[IssueClientTokenCommand, TokenGranted | TokenDenied]
):
    """OAuth 2.0 client credentials (S6.2). Returns the denial instead of
    raising it, so the request's transaction keeps the failed attempt in the
    client's usage of the day."""

    def __init__(
        self,
        clients: IntegrationClientRepository,
        secrets: ClientSecretRepository,
        usage: IntegrationUsageRepository,
        tenants: TenantRepository,
        tokens: TokenService,
        plan: IntegrationPlan,
        settings: IntegrationSettings,
    ):
        self.clients = clients
        self.secrets = secrets
        self.usage = usage
        self.tenants = tenants
        self.tokens = tokens
        self.plan = plan
        self.settings = settings

    def _handle(self, command: IssueClientTokenCommand) -> TokenGranted | TokenDenied:
        now = datetime.now()
        client = self.clients.first(public_id=command.public_id)
        if client is None:
            decoy_check(command.client_secret)
            return self._deny(command, None, now, INVALID_CLIENT, "unknown client")
        secret = _matching(
            self.secrets.of_clients([client.require_id()]), command.client_secret
        )
        if secret is None:
            return self._deny(command, client, now, INVALID_CLIENT, "wrong secret")
        reason = self._refusal(client, secret, command, now)
        if reason is not None:
            return self._deny(command, client, now, INVALID_CLIENT, reason)

        allowed = client.scopes & self.plan.allowed_scopes()
        scopes = self._scopes(command.scope, allowed)
        if scopes is None:
            # The client did authenticate: it may know why
            return self._deny(
                command,
                client,
                now,
                INVALID_SCOPE,
                "scope not granted" if command.scope else "no scope left",
                "the requested scope is unknown or not granted to the client",
            )

        token = self.tokens.issue_client_access(
            public_id=client.public_id,
            tenant_id=require_tenant("issuing a client token").tenant_id,
            secret_id=secret.require_id(),
            scopes=scopes,
            branch_ids=client.branch_ids,
        )
        # The day's usage before the client's row, the order of each request's
        # usage (`record_request`): the other way round they deadlock (S9.2)
        self.usage.count(client.require_id(), at=now, ip=command.ip, token_requests=1)
        secret.record_use(now)
        self.secrets.update(secret)
        client.record_use(now)
        self.clients.update(client)
        logger.info(
            "integration_token_issued",
            client_id=client.public_id,
            scope=format_scopes(scopes),
        )
        return TokenGranted(
            access_token=token.access_token,
            expires_in=token.expires_in,
            scope=format_scopes(scopes),
        )

    def _refusal(
        self,
        client: IntegrationClient,
        secret: ClientSecret,
        command: IssueClientTokenCommand,
        now: datetime,
    ) -> str | None:
        if not client.is_active:
            return "client revoked"
        if not secret.is_active(now):
            return "secret revoked or expired"
        if client.environment != self.settings.environment:
            return f"client of the {client.environment} environment"
        if not client.allows_ip(command.ip):
            return "address not allowed"
        tenant = self.tenants.get(require_tenant().tenant_id)
        if tenant is None or tenant.status != TenantStatus.ACTIVE:
            return "tenant not active"
        return None

    @staticmethod
    def _scopes(
        requested: str | None, allowed: frozenset[Scope]
    ) -> frozenset[Scope] | None:
        """The requested scopes if the client has them all; without a request,
        all of its own. None: nothing to grant"""
        if not requested:
            return allowed or None
        try:
            scopes = parse_scopes(requested)
        except ValueError:
            return None
        return scopes if scopes and scopes <= allowed else None

    def _deny(
        self,
        command: IssueClientTokenCommand,
        client: IntegrationClient | None,
        now: datetime,
        error: str,
        reason: str,
        description: str = "client authentication failed",
    ) -> TokenDenied:
        if client is not None:
            self.usage.count(
                client.require_id(), at=now, ip=command.ip, token_failures=1
            )
        logger.info(
            "integration_token_denied", client_id=command.public_id, reason=reason
        )
        return TokenDenied(error, reason, description)


def _matching(secrets: list[ClientSecret], plain: str) -> ClientSecret | None:
    """The secret it matches, comparing with every one so the time doesn't
    depend on which"""
    found = None
    for secret in secrets:
        if secret.matches(plain) and found is None:
            found = secret
    return found
