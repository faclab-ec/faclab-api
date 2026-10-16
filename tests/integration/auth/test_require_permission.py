from uuid import uuid4

import pytest

from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import PermissionDeniedError
from src.auth.domain.permissions import Permission, permissions_for
from src.auth.infra.dependencies import require_permission


def _make_user(role: Role) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=1,
        username="testuser",
        role=role,
        tenant_id=uuid4(),
        permissions=permissions_for(role),
    )


def test_admin_passes_all_permissions():
    admin = _make_user(Role.ADMIN)
    dep = require_permission(Permission.USER_MANAGE)
    result = dep(user=admin)
    assert result.role == Role.ADMIN


def test_viewer_blocked_on_write_permissions():
    viewer = _make_user(Role.VIEWER)
    dep = require_permission(Permission.PRODUCT_WRITE)
    with pytest.raises(PermissionDeniedError):
        dep(user=viewer)


def test_operator_passes_sale_read():
    operator = _make_user(Role.OPERATOR)
    dep = require_permission(Permission.SALE_READ)
    result = dep(user=operator)
    assert result.role == Role.OPERATOR


def test_operator_blocked_on_sale_cancel():
    operator = _make_user(Role.OPERATOR)
    dep = require_permission(Permission.SALE_CANCEL)
    with pytest.raises(PermissionDeniedError):
        dep(user=operator)


def test_manager_passes_product_write():
    manager = _make_user(Role.MANAGER)
    dep = require_permission(Permission.PRODUCT_WRITE)
    result = dep(user=manager)
    assert result.role == Role.MANAGER


def test_viewer_blocked_on_user_manage():
    viewer = _make_user(Role.VIEWER)
    dep = require_permission(Permission.USER_MANAGE)
    with pytest.raises(PermissionDeniedError):
        dep(user=viewer)
