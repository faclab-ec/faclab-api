from fastapi import Depends, Header, Request

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.exceptions import (
    BranchAccessDeniedError,
    BranchRequiredError,
    InvalidBranchHeaderError,
    InvalidTokenError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import Permission


def get_optional_user(request: Request) -> AuthenticatedUser | None:
    return getattr(request.state, "current_user", None)


def get_current_user(request: Request) -> AuthenticatedUser:
    """The request's user. A request with an `X-Branch-Id` the user can't use
    fails here, so on every authenticated route."""
    user = getattr(request.state, "current_user", None)
    if user is not None:
        branch_error = getattr(request.state, "branch_error", None)
        if branch_error == "invalid":
            raise InvalidBranchHeaderError()
        if branch_error == "denied":
            raise BranchAccessDeniedError()
        return user

    reason = getattr(request.state, "auth_error", None)
    if reason == "token_expired":
        raise TokenExpiredError("access token expired")
    if reason == "invalid_token":
        raise InvalidTokenError("invalid access token")
    if reason == "tenant_required":
        raise TenantRequiredError()
    raise PermissionDeniedError("authentication required")


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


def require_branch(
    request: Request,
    # Authenticates the request and rejects a header the user can't use
    user: AuthenticatedUser = Depends(get_current_user),
    branch: str | None = Header(
        None,
        alias="X-Branch-Id",
        description=(
            "Branch of the operation, one the user may enter "
            "(`BRANCH_ACCESS_DENIED`, 403)"
        ),
    ),
) -> int:
    """The branch of a branch operation: `X-Branch-Id`, already checked against
    the user's branches by `AuthMiddleware` (`BRANCH_REQUIRED` without it)."""
    branch_id = getattr(request.state, "branch_id", None)
    if branch is None or branch_id is None:
        raise BranchRequiredError()
    return branch_id
