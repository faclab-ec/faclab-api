from unittest.mock import Mock

import pytest

from src.auth.domain.entities import Role, User
from src.shared.domain.exceptions import InvalidValueError
from src.tenancy.app.commands.provision_tenant import (
    ProvisionTenantCommand,
    ProvisionTenantCommandHandler,
)
from src.tenancy.domain.entities import Membership, Tenant
from src.tenancy.domain.exceptions import AdminPasswordRequiredError

RUC = "1799999990001"


def _command(**overrides) -> ProvisionTenantCommand:
    defaults = {
        "ruc": RUC,
        "legal_name": "Ferretería S.A.",
        "admin_username": "ana",
        "admin_email": "ana@example.com",
        "admin_password": "Secret123",
    }
    defaults.update(overrides)
    return ProvisionTenantCommand(**defaults)


def _handler(tenant=None, user=None, membership=None):
    tenants = Mock()
    tenants.get_by_ruc.return_value = tenant
    tenants.add.side_effect = lambda t: t
    memberships = Mock()
    memberships.get_for.return_value = membership
    users = Mock()
    users.get_by_username.return_value = user
    create_user = Mock()
    create_user.handle.return_value = {"id": 5}
    handler = ProvisionTenantCommandHandler(tenants, memberships, users, create_user)
    return handler, tenants, memberships, create_user


def test_creates_the_tenant_and_its_admin():
    handler, tenants, memberships, create_user = _handler()

    result = handler.handle(_command(trade_name="La Ferre"))

    [tenant] = tenants.add.call_args.args
    assert (tenant.ruc, tenant.trade_name) == (RUC, "La Ferre")
    [command] = create_user.handle.call_args.args
    assert command.tenant_id == tenant.id
    assert (command.username, command.role) == ("ana", Role.ADMIN.value)
    assert result == {
        "tenant_id": tenant.id,
        "tenant_created": True,
        "user_id": 5,
        "user_created": True,
        "membership_created": True,
    }


def test_running_it_again_changes_nothing():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería S.A.")
    admin = Membership(tenant_id=tenant.id, user_id=5, role=Role.ADMIN)
    handler, tenants, memberships, create_user = _handler(
        tenant=tenant,
        user=User(id=5, username="ana", email="ana@example.com", password_hash="h"),
        membership=admin,
    )

    result = handler.handle(_command(admin_password=None))

    tenants.add.assert_not_called()
    create_user.handle.assert_not_called()
    memberships.create.assert_not_called()
    memberships.update.assert_not_called()
    assert (result["tenant_created"], result["user_created"]) == (False, False)
    assert result["membership_created"] is False


def test_an_existing_user_joins_the_tenant_with_its_own_password():
    handler, tenants, memberships, create_user = _handler(
        user=User(id=8, username="ana", email="ana@example.com", password_hash="h")
    )

    result = handler.handle(_command(admin_password=None))

    [membership] = memberships.create.call_args.args
    assert (membership.user_id, membership.role) == (8, Role.ADMIN)
    assert membership.tenant_id == result["tenant_id"]
    create_user.handle.assert_not_called()
    assert (result["user_created"], result["membership_created"]) == (False, True)


def test_an_existing_membership_becomes_an_active_admin():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería S.A.")
    membership = Membership(
        tenant_id=tenant.id, user_id=8, role=Role.CASHIER, active=False
    )
    handler, _, memberships, _ = _handler(
        tenant=tenant,
        user=User(id=8, username="ana", email="ana@example.com", password_hash="h"),
        membership=membership,
    )

    handler.handle(_command())

    memberships.update.assert_called_once_with(membership)
    assert (membership.role, membership.active) == (Role.ADMIN, True)


def test_a_new_admin_needs_a_password():
    handler, _, _, create_user = _handler()

    with pytest.raises(AdminPasswordRequiredError) as exc:
        handler.handle(_command(admin_password=None))

    assert exc.value.error_code == "VALIDATION_ERROR"
    create_user.handle.assert_not_called()


def test_an_invalid_ruc_creates_nothing():
    handler, tenants, _, create_user = _handler()

    with pytest.raises(InvalidValueError):
        handler.handle(_command(ruc="1710034065"))

    tenants.get_by_ruc.assert_not_called()
    create_user.handle.assert_not_called()
