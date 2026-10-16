from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.app.services.token_service import TokenService
from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import permissions_for


class AuthMiddleware(BaseHTTPMiddleware):
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
            except InvalidTokenError:
                request.state.auth_error = "invalid_token"

        return await call_next(request)
