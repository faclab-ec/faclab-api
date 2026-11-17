from fastapi import Depends, Header, Request

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.exceptions import (
    BranchAccessDeniedError,
    BranchRequiredError,
    InsufficientScopeError,
    IntegrationNotAllowedError,
    InvalidBranchHeaderError,
    InvalidTokenError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import Permission
from src.auth.domain.principals import IntegrationPrincipal, Principal
from src.auth.domain.scopes import Scope


def get_optional_user(request: Request) -> AuthenticatedUser | None:
    return getattr(request.state, "current_user", None)


def get_principal(request: Request) -> Principal:
    """Who makes the request: a user or an integration client (S6.2). A request
    with an `X-Branch-Id` the principal can't use fails here, so on every
    authenticated route."""
    principal = getattr(request.state, "current_user", None) or getattr(
        request.state, "integration", None
    )
    if principal is not None:
        branch_error = getattr(request.state, "branch_error", None)
        if branch_error == "invalid":
            raise InvalidBranchHeaderError()
        if branch_error == "denied":
            raise BranchAccessDeniedError()
        return principal

    reason = getattr(request.state, "auth_error", None)
    if reason == "token_expired":
        raise TokenExpiredError("access token expired")
    if reason == "invalid_token":
        raise InvalidTokenError("invalid access token")
    if reason == "tenant_required":
        raise TenantRequiredError()
    raise PermissionDeniedError("authentication required")


def get_current_user(request: Request) -> AuthenticatedUser:
    """The request's user. The routes of the frontend (/api/admin, /api/pos,
    /api/auth) are only for people: an integration's token gets
    `INTEGRATION_NOT_ALLOWED` (403) and uses the public API instead."""
    principal = get_principal(request)
    if isinstance(principal, IntegrationPrincipal):
        raise IntegrationNotAllowedError()
    return principal


def require_permission(*required: Permission):
    def _dep(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.must_change_password:
            raise PasswordChangeRequiredError(
                "password change required before any other action"
            )
        if not set(required).issubset(user.permissions):
            missing = [p.value for p in required if p not in user.permissions]
            raise PermissionDeniedError(f"missing permissions: {missing}")
        return user

    return _dep


def require_scope(*required: Scope):
    """The integration client of the request, with every scope of `required`
    (`INSUFFICIENT_SCOPE`, 403). The routes that integrations call (the public
    API, S6.3) declare it as the frontend's declare `require_permission`; a
    user's token gets `PERMISSION_DENIED`."""

    def _dep(principal: Principal = Depends(get_principal)) -> IntegrationPrincipal:
        if not isinstance(principal, IntegrationPrincipal):
            raise PermissionDeniedError("this route takes integration credentials")
        if not principal.has_scopes(*required):
            missing = sorted(s.value for s in required if s not in principal.scopes)
            raise InsufficientScopeError(missing)
        return principal

    return _dep


def require_branch(
    request: Request,
    # Authenticates the request and rejects a header the principal can't use
    principal: Principal = Depends(get_principal),
    branch: str | None = Header(
        None,
        alias="X-Branch-Id",
        description=(
            "Branch of the operation, one the user (or integration) may enter "
            "(`BRANCH_ACCESS_DENIED`, 403)"
        ),
    ),
) -> int:
    """The branch of a branch operation: `X-Branch-Id`, already checked against
    the principal's branches by `AuthMiddleware` (`BRANCH_REQUIRED` without it).
    A user's route also declares `require_permission`, which rejects an
    integration."""
    branch_id = getattr(request.state, "branch_id", None)
    if branch is None or branch_id is None:
        raise BranchRequiredError()
    return branch_id
