from fastapi import Depends, Request

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.exceptions import (
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
    user = getattr(request.state, "current_user", None)
    if user is not None:
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
