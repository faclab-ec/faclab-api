from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.app.services.token_service import TokenService
from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import permissions_for
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope


class AuthMiddleware(BaseHTTPMiddleware):
    """Reads the Bearer access token into `request.state.current_user` and runs
    the rest of the request in the token's tenant (`TenantContext`).

    It never rejects: an invalid token only records why in
    `request.state.auth_error`, and `require_permission` answers 401/403 on the
    routes that need a user."""

    def __init__(self, app, token_service: TokenService):
        super().__init__(app)
        self._token_service = token_service

    async def dispatch(self, request, call_next):
        request.state.current_user = None
        request.state.auth_error = None

        header = request.headers.get("authorization")
        if header and header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1].strip()
            try:
                claims = self._token_service.decode_access(token)
                if claims.role is None or claims.tid is None:
                    raise InvalidTokenError("invalid token")
                role = Role(claims.role)
                request.state.current_user = AuthenticatedUser(
                    id=claims.sub,
                    username=claims.username,
                    role=role,
                    tenant_id=claims.tid,
                    permissions=permissions_for(role),
                    must_change_password=claims.must_change_password,
                    session_id=claims.sid,
                    full_name=claims.name,
                )
            except TokenExpiredError:
                request.state.auth_error = "token_expired"
            except TenantRequiredError:
                request.state.auth_error = "tenant_required"
            except (InvalidTokenError, ValueError):
                # ValueError: a signed token with a role that doesn't exist
                request.state.auth_error = "invalid_token"

        user = request.state.current_user
        if user is None:
            return await call_next(request)
        context = TenantContext(user.tenant_id, TenantSource.REQUEST, user_id=user.id)
        with tenant_scope(context):
            return await call_next(request)
