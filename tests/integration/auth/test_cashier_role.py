from uuid import uuid4

import pytest

from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import PermissionDeniedError
from src.auth.domain.permissions import Permission, permissions_for
from src.auth.infra.dependencies import require_permission


def _make_user(role: Role) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=1,
        username="cashier01",
        role=role,
        tenant_id=uuid4(),
        permissions=permissions_for(role),
    )


def test_cashier_passes_pos_operate():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.POS_OPERATE)
    assert dep(user=cashier).role == Role.CASHIER


def test_cashier_passes_sale_write():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.SALE_WRITE)
    assert dep(user=cashier).role == Role.CASHIER


def test_cashier_passes_customer_write():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.CUSTOMER_WRITE)
    assert dep(user=cashier).role == Role.CASHIER


def test_cashier_passes_report_pos_read():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.REPORT_POS_READ)
    assert dep(user=cashier).role == Role.CASHIER


def test_cashier_blocked_on_user_manage():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.USER_MANAGE)
    with pytest.raises(PermissionDeniedError):
        dep(user=cashier)


def test_cashier_blocked_on_purchase_write():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.PURCHASE_WRITE)
    with pytest.raises(PermissionDeniedError):
        dep(user=cashier)


def test_cashier_blocked_on_adjustment_write():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.ADJUSTMENT_WRITE)
    with pytest.raises(PermissionDeniedError):
        dep(user=cashier)


def test_cashier_blocked_on_refund_approve():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.REFUND_APPROVE)
    with pytest.raises(PermissionDeniedError):
        dep(user=cashier)


def test_cashier_blocked_on_sale_cancel():
    cashier = _make_user(Role.CASHIER)
    dep = require_permission(Permission.SALE_CANCEL)
    with pytest.raises(PermissionDeniedError):
        dep(user=cashier)


def test_operator_blocked_on_pos_operate():
    operator = _make_user(Role.OPERATOR)
    dep = require_permission(Permission.POS_OPERATE)
    with pytest.raises(PermissionDeniedError):
        dep(user=operator)


def test_manager_blocked_on_pos_operate():
    manager = _make_user(Role.MANAGER)
    dep = require_permission(Permission.POS_OPERATE)
    with pytest.raises(PermissionDeniedError):
        dep(user=manager)


def test_manager_passes_refund_approve():
    manager = _make_user(Role.MANAGER)
    dep = require_permission(Permission.REFUND_APPROVE)
    assert dep(user=manager).role == Role.MANAGER
