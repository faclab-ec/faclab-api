"""`POST /api/oauth/token`: OAuth 2.0 client credentials (RFC 6749 §4.4, S6.2).

Public: the client authenticates with its client_id and secret, with HTTP
Basic (`client_secret_basic`, preferred) or in the form (`client_secret_post`),
never both. The answers follow RFC 6749 §5 instead of the API's envelope, so
any OAuth library can use them: `{"access_token", "token_type", "expires_in",
"scope"}`, or `{"error", "error_description"}` with 400 or 401.

The tenant comes from the client_id: the directory says which one, and the
command runs in it before the request's session opens its transaction, so
row-level security applies to everything it reads.
"""

import base64
import binascii
from dataclasses import dataclass
from urllib.parse import unquote

import structlog
from fastapi import APIRouter, Form, Header, Request
from fastapi.responses import JSONResponse
from wireup import Injected

from config import config
from src.integrations.app.commands.token import (
    INVALID_CLIENT,
    IssueClientTokenCommand,
    IssueClientTokenCommandHandler,
    TokenDenied,
)
from src.integrations.domain.credentials import decoy_check, is_public_id
from src.integrations.infra.access import CachedIntegrationAccess
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope

logger = structlog.get_logger(__name__)

TOKEN_PATH = "/api/oauth/token"
GRANT_TYPE = "client_credentials"
# RFC 6749 §5.1: a token response is never cached
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@dataclass(frozen=True)
class _Credentials:
    client_id: str
    client_secret: str


class _OAuthError(Exception):
    def __init__(self, status: int, error: str, description: str):
        self.status = status
        self.error = error
        self.description = description


class OAuthRouter:
    def __init__(self, access: CachedIntegrationAccess):
        self._access = access
        self.router = APIRouter()
        self.router.add_api_route(
            TOKEN_PATH,
            self.token,
            methods=["POST"],
            summary="Integration access token (OAuth 2.0 client credentials)",
            tags=["OAuth"],
            response_model=None,
            responses={
                200: {"description": "access_token, token_type, expires_in, scope"},
                400: {
                    "description": "invalid_request, unsupported_grant_type, "
                    "invalid_scope"
                },
                401: {"description": "invalid_client"},
                503: {"description": "temporarily_unavailable: integrations disabled"},
            },
        )

    def token(
        self,
        request: Request,
        handler: Injected[IssueClientTokenCommandHandler],
        grant_type: str | None = Form(None, description="client_credentials"),
        scope: str | None = Form(
            None,
            description="Scopes wanted, separated by spaces; default all of the "
            "client's",
        ),
        client_id: str | None = Form(
            None, description="Only without HTTP Basic (client_secret_post)"
        ),
        client_secret: str | None = Form(
            None, description="Only without HTTP Basic (client_secret_post)"
        ),
        authorization: str | None = Header(
            None, description="Basic base64(client_id:client_secret)"
        ),
    ) -> JSONResponse:
        """An access token for an integration client: 15 minutes, no refresh
        (it asks again with its credentials). Its claims carry the tenant
        (`tid`), the client (`azp`), the `scope` granted and the branches it is
        limited to (`bids`). Answers follow RFC 6749, not the API envelope."""
        try:
            if not config.INTEGRATIONS_ENABLED:
                raise _OAuthError(
                    503, "temporarily_unavailable", "integrations are disabled"
                )
            if not grant_type:
                raise _OAuthError(400, "invalid_request", "grant_type is required")
            if grant_type != GRANT_TYPE:
                raise _OAuthError(
                    400, "unsupported_grant_type", "only client_credentials"
                )
            credentials = _credentials(authorization, client_id, client_secret)
            result = self._issue(request, handler, credentials, scope)
            if isinstance(result, TokenDenied):
                status = 401 if result.error == INVALID_CLIENT else 400
                raise _OAuthError(status, result.error, result.description)
        except _OAuthError as exc:
            return _error(exc)
        return JSONResponse(
            {
                "access_token": result.access_token,
                "token_type": "Bearer",
                "expires_in": result.expires_in,
                "scope": result.scope,
            },
            headers=_NO_STORE,
        )

    def _issue(
        self,
        request: Request,
        handler: IssueClientTokenCommandHandler,
        credentials: _Credentials,
        scope: str | None,
    ):
        tenant_id = (
            self._access.tenant_of(credentials.client_id)
            if is_public_id(credentials.client_id)
            else None
        )
        if tenant_id is None:
            decoy_check(credentials.client_secret)
            logger.info(
                "integration_token_denied",
                client_id=credentials.client_id[:32],
                reason="unknown client",
            )
            raise _OAuthError(401, INVALID_CLIENT, "client authentication failed")
        context = TenantContext(tenant_id, TenantSource.REQUEST)
        with tenant_scope(context):
            return handler.handle(
                IssueClientTokenCommand(
                    public_id=credentials.client_id,
                    client_secret=credentials.client_secret,
                    scope=scope,
                    ip=request.client.host if request.client else None,
                )
            )


def _credentials(
    authorization: str | None, client_id: str | None, client_secret: str | None
) -> _Credentials:
    """The client's credentials, from one method only (RFC 6749 §2.3)"""
    if authorization and authorization.lower().startswith("basic "):
        if client_secret is not None:
            raise _OAuthError(
                400, "invalid_request", "use HTTP Basic or the form, not both"
            )
        basic = _basic(authorization)
        if client_id is not None and client_id != basic.client_id:
            raise _OAuthError(
                400, "invalid_request", "client_id differs from HTTP Basic's"
            )
        return basic
    if not client_id or not client_secret:
        raise _OAuthError(401, INVALID_CLIENT, "send client_id and client_secret")
    return _Credentials(client_id, client_secret)


def _basic(authorization: str) -> _Credentials:
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1].strip()).decode()
        client_id, client_secret = decoded.split(":", 1)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise _OAuthError(401, INVALID_CLIENT, "malformed Basic credentials") from None
    # Both go form-urlencoded inside Basic (RFC 6749 §2.3.1)
    return _Credentials(unquote(client_id), unquote(client_secret))


def _error(exc: _OAuthError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if exc.status == 401:
        # Required with HTTP Basic, and the method a client should try
        headers["WWW-Authenticate"] = 'Basic realm="faclab"'
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status,
        headers=headers,
    )
