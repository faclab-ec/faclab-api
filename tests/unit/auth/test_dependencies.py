from types import SimpleNamespace
from uuid import UUID

import pytest

from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import (
    BranchAccessDeniedError,
    InsufficientScopeError,
    IntegrationNotAllowedError,
    InvalidTokenError,
    PasswordChangeRequiredError,
    PermissionDeniedError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import Permission
from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.auth.infra.dependencies import (
    get_current_user,
    get_optional_user,
    get_principal,
    require_permission,
    require_scope,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _request(**state):
    return SimpleNamespace(state=SimpleNamespace(**state))


def _admin() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=1,
        username="admin",
        role=Role.ADMIN,
        tenant_id=TENANT,
        permissions=frozenset({Permission.USER_MANAGE}),
    )


def test_get_optional_user_returns_none_when_missing():
    assert get_optional_user(_request(current_user=None)) is None


def test_get_optional_user_returns_user_when_present():
    user = _admin()
    assert get_optional_user(_request(current_user=user)) is user


def test_get_current_user_raises_permission_denied_when_no_header():
    with pytest.raises(PermissionDeniedError):
        get_current_user(_request(current_user=None, auth_error=None))


def test_get_current_user_raises_token_expired():
    with pytest.raises(TokenExpiredError):
        get_current_user(_request(current_user=None, auth_error="token_expired"))


def test_get_current_user_raises_invalid_token():
    with pytest.raises(InvalidTokenError):
        get_current_user(_request(current_user=None, auth_error="invalid_token"))


def test_get_current_user_raises_tenant_required():
    with pytest.raises(TenantRequiredError):
        get_current_user(_request(current_user=None, auth_error="tenant_required"))


def test_get_current_user_returns_user():
    user = _admin()
    assert get_current_user(_request(current_user=user)) is user


def test_require_permission_allows_when_user_has_all():
    user = _admin()
    dep = require_permission(Permission.USER_MANAGE)
    assert dep(user=user) is user


def test_require_permission_raises_when_missing():
    user = AuthenticatedUser(
        id=2,
        username="viewer",
        role=Role.VIEWER,
        tenant_id=TENANT,
        permissions=frozenset(),
    )
    dep = require_permission(Permission.USER_MANAGE)
    with pytest.raises(PermissionDeniedError):
        dep(user=user)


def test_require_permission_blocks_when_must_change_password():
    user = AuthenticatedUser(
        id=3,
        username="cashier",
        role=Role.CASHIER,
        tenant_id=TENANT,
        permissions=frozenset({Permission.POS_OPERATE}),
        must_change_password=True,
    )
    dep = require_permission(Permission.POS_OPERATE)
    with pytest.raises(PasswordChangeRequiredError):
        dep(user=user)


def _integration(*scopes: Scope) -> IntegrationPrincipal:
    return IntegrationPrincipal(
        client_id=9,
        public_id="fl_test_0123456789ab",
        name="Tienda web",
        tenant_id=TENANT,
        scopes=frozenset(scopes),
    )


def test_get_principal_returns_the_integration():
    integration = _integration(Scope.STOCK_READ)

    assert get_principal(_request(current_user=None, integration=integration)) is (
        integration
    )


def test_get_principal_rejects_a_branch_the_integration_cant_use():
    request = _request(
        current_user=None, integration=_integration(), branch_error="denied"
    )

    with pytest.raises(BranchAccessDeniedError):
        get_principal(request)


def test_get_current_user_rejects_an_integration():
    request = _request(current_user=None, integration=_integration(*Scope))

    with pytest.raises(IntegrationNotAllowedError):
        get_current_user(request)


def test_require_scope_needs_every_scope():
    dep = require_scope(Scope.SALES_WRITE, Scope.STOCK_READ)
    integration = _integration(Scope.SALES_WRITE, Scope.STOCK_READ)

    assert dep(integration) is integration
    with pytest.raises(InsufficientScopeError):
        dep(_integration(Scope.SALES_WRITE))


def test_require_scope_rejects_a_user():
    with pytest.raises(PermissionDeniedError):
        require_scope(Scope.STOCK_READ)(_admin())
