import re

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

BRANCH_HEADER = "X-Branch-Id"
# A positive id that fits the branches' integer key
_BRANCH_ID = re.compile(r"[1-9][0-9]{0,9}")
_MAX_ID = 2**31 - 1


class AuthMiddleware(BaseHTTPMiddleware):
    """Reads the Bearer access token into `request.state.current_user` and runs
    the rest of the request in the token's tenant (`TenantContext`).

    It never rejects: an invalid token only records why in
    `request.state.auth_error`, and `require_permission` answers 401/403 on the
    routes that need a user.

    A request of a user with `X-Branch-Id` also runs in that branch
    (`TenantContext.branch_id`, `request.state.branch_id`) when the user may
    enter it (claim `bids`); otherwise `request.state.branch_error` says why and
    `get_current_user` answers 422 or 403. That the branch exists and is active
    is checked by the operations that need it."""

    def __init__(self, app, token_service: TokenService):
        super().__init__(app)
        self._token_service = token_service

    async def dispatch(self, request, call_next):
        request.state.current_user = None
        request.state.auth_error = None
        request.state.branch_id = None
        request.state.branch_error = None

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
                    branch_ids=claims.bids,
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
        branch_id = _branch(request, user)
        context = TenantContext(
            user.tenant_id, TenantSource.REQUEST, user_id=user.id, branch_id=branch_id
        )
        with tenant_scope(context):
            return await call_next(request)


def _branch(request, user: AuthenticatedUser) -> int | None:
    """The branch of `X-Branch-Id` if the user may enter it"""
    header = request.headers.get(BRANCH_HEADER)
    if header is None:
        return None
    value = header.strip()
    if not _BRANCH_ID.fullmatch(value) or int(value) > _MAX_ID:
        request.state.branch_error = "invalid"
        return None
    branch_id = int(value)
    if not user.can_enter_branch(branch_id):
        request.state.branch_error = "denied"
        return None
    request.state.branch_id = branch_id
    return branch_id
