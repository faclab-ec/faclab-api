import re
from contextlib import nullcontext

import structlog
from opentelemetry import trace
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.app.services.integration_access import IntegrationAccess
from src.auth.app.services.token_service import (
    ClientTokenClaims,
    PlatformTokenClaims,
    TokenService,
)
from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import permissions_for
from src.auth.domain.principals import (
    IntegrationPrincipal,
    PlatformPrincipal,
    Principal,
)
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope

logger = structlog.get_logger(__name__)

BRANCH_HEADER = "X-Branch-Id"
# The integration client of the request (its public client_id), in logs and span
INTEGRATION_ATTRIBUTE = "faclab.integration.client_id"
# A positive id that fits the branches' integer key
_BRANCH_ID = re.compile(r"[1-9][0-9]{0,9}")
_MAX_ID = 2**31 - 1


class AuthMiddleware(BaseHTTPMiddleware):
    """Reads the Bearer access token into `request.state.current_user` (a
    person) or `request.state.integration` (an integration client, S6.2) and
    runs the rest of the request in the token's tenant (`TenantContext`).

    A platform operator's token (S8.5) has no tenant: it sets
    `request.state.platform_operator` and the request runs without a
    `TenantContext`; `/api/platform` routes read it, any other authenticated
    route answers `PLATFORM_NOT_ALLOWED`.

    It never rejects: an invalid token only records why in
    `request.state.auth_error`, and the route's dependencies answer 401/403.

    An integration's token is checked against the client's current state
    (`IntegrationAccess`, cached for at most a minute): a revoked client or
    secret makes it invalid, and its scopes and branches are narrowed to the
    client's. Every request of an integration counts in its usage. Without
    `integrations` (or with them disabled) such a token is invalid.

    A request with `X-Branch-Id` also runs in that branch
    (`TenantContext.branch_id`, `request.state.branch_id`) when the principal
    may enter it (claim `bids`); otherwise `request.state.branch_error` says why
    and `get_principal` answers 422 or 403. That the branch exists and is
    active is checked by the operations that need it."""

    def __init__(
        self,
        app,
        token_service: TokenService,
        integrations: IntegrationAccess | None = None,
    ):
        super().__init__(app)
        self._token_service = token_service
        self._integrations = integrations

    async def dispatch(self, request, call_next):
        request.state.current_user = None
        request.state.integration = None
        request.state.platform_operator = None
        request.state.auth_error = None
        request.state.branch_id = None
        request.state.branch_error = None

        principal = await self._principal(request)
        if principal is None:
            return await call_next(request)

        branch_id = _branch(request, principal)
        if isinstance(principal, IntegrationPrincipal):
            integration, user_id = principal, None
        else:
            integration, user_id = None, principal.id
        context = TenantContext(
            principal.tenant_id,
            TenantSource.REQUEST,
            user_id=user_id,
            branch_id=branch_id,
            user_name=principal.display_name,
            integration_id=integration.client_id if integration else None,
        )
        with tenant_scope(context), _integration_scope(integration):
            response = await call_next(request)
            if integration is not None and self._integrations is not None:
                await run_in_threadpool(
                    self._integrations.record_request,
                    integration,
                    response.status_code,
                    _client_ip(request),
                )
            return response

    async def _principal(self, request) -> Principal | None:
        header = request.headers.get("authorization")
        if not header or not header.lower().startswith("bearer "):
            return None
        token = header.split(" ", 1)[1].strip()
        try:
            claims = self._token_service.decode_bearer(token)
            if isinstance(claims, PlatformTokenClaims):
                request.state.platform_operator = PlatformPrincipal(
                    user_id=claims.sub, username=claims.username, full_name=claims.name
                )
                return None
            if isinstance(claims, ClientTokenClaims):
                integration = await self._integration(claims, request)
                if integration is None:
                    raise InvalidTokenError("invalid token")
                request.state.integration = integration
                return integration
            if claims.role is None or claims.tid is None:
                raise InvalidTokenError("invalid token")
            role = Role(claims.role)
            user = AuthenticatedUser(
                id=claims.sub,
                username=claims.username,
                role=role,
                tenant_id=claims.tid,
                permissions=permissions_for(role),
                must_change_password=claims.must_change_password,
                session_id=claims.sid,
                full_name=claims.name,
                branch_ids=claims.bids,
            )
            request.state.current_user = user
            return user
        except TokenExpiredError:
            request.state.auth_error = "token_expired"
        except TenantRequiredError:
            request.state.auth_error = "tenant_required"
        except (InvalidTokenError, ValueError):
            # ValueError: a signed token with a role that doesn't exist
            request.state.auth_error = "invalid_token"
        return None

    async def _integration(
        self, claims: ClientTokenClaims, request
    ) -> IntegrationPrincipal | None:
        if self._integrations is None:
            logger.info("integration_token_rejected", reason="integrations disabled")
            return None
        try:
            return await run_in_threadpool(
                self._integrations.principal, claims, _client_ip(request)
            )
        except Exception:
            # Fails closed: without the client's state the token isn't trusted
            logger.exception("integration_access_failed", client_id=claims.public_id)
            return None


def _integration_scope(integration: IntegrationPrincipal | None):
    if integration is None:
        return nullcontext()
    trace.get_current_span().set_attribute(INTEGRATION_ATTRIBUTE, integration.public_id)
    return structlog.contextvars.bound_contextvars(
        **{INTEGRATION_ATTRIBUTE: integration.public_id}
    )


def _client_ip(request) -> str | None:
    """The client's address; behind the proxy, the one it forwarded
    (uvicorn's `--forwarded-allow-ips`)"""
    return request.client.host if request.client else None


def _branch(request, principal: Principal) -> int | None:
    """The branch of `X-Branch-Id` if the principal may enter it"""
    header = request.headers.get(BRANCH_HEADER)
    if header is None:
        return None
    value = header.strip()
    if not _BRANCH_ID.fullmatch(value) or int(value) > _MAX_ID:
        request.state.branch_error = "invalid"
        return None
    branch_id = int(value)
    if not principal.can_enter_branch(branch_id):
        request.state.branch_error = "denied"
        return None
    request.state.branch_id = branch_id
    return branch_id
