from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest

from src.auth.app.commands.activate_user import (
    ActivateUserCommand,
    ActivateUserCommandHandler,
)
from src.auth.app.commands.deactivate_user import (
    DeactivateUserCommand,
    DeactivateUserCommandHandler,
)
from src.auth.app.commands.update_user_role import (
    UpdateUserRoleCommand,
    UpdateUserRoleCommandHandler,
)
from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import LastAdminError
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.domain.entities import Membership

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _make_user(**overrides):
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hashed",
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _membership(**overrides) -> Membership:
    defaults: dict[str, Any] = {
        "id": 9,
        "tenant_id": TENANT,
        "user_id": 1,
        "role": Role.VIEWER,
        "active": True,
    }
    defaults.update(overrides)
    return Membership(**defaults)


def _repos(user=None, membership=None, admins=1):
    users = Mock()
    users.get_by_id.return_value = user if user is not None else _make_user()
    memberships = Mock()
    memberships.get_for.return_value = membership
    memberships.update.side_effect = lambda m: m
    memberships.lock_active_admins.return_value = admins
    return users, memberships


def test_update_user_role_changes_the_membership():
    users, memberships = _repos(membership=_membership(role=Role.VIEWER))

    handler = UpdateUserRoleCommandHandler(users, memberships)
    result = handler.handle(
        UpdateUserRoleCommand(tenant_id=TENANT, user_id=1, role=Role.MANAGER.value)
    )

    assert result["role"] == Role.MANAGER
    assert result["username"] == "testuser"
    memberships.get_for.assert_called_once_with(TENANT, 1, for_update=True)
    assert memberships.update.call_args.args[0].role == Role.MANAGER
    users.update.assert_not_called()


@pytest.mark.parametrize(
    "call",
    [
        lambda users, memberships: UpdateUserRoleCommandHandler(
            users, memberships
        ).handle(UpdateUserRoleCommand(tenant_id=TENANT, user_id=999, role=1)),
        lambda users, memberships: DeactivateUserCommandHandler(
            users, Mock(), memberships
        ).handle(DeactivateUserCommand(tenant_id=TENANT, user_id=999)),
        lambda users, memberships: ActivateUserCommandHandler(
            users, memberships
        ).handle(ActivateUserCommand(tenant_id=TENANT, user_id=999)),
    ],
    ids=["role", "deactivate", "activate"],
)
def test_a_user_of_another_tenant_is_not_found(call):
    users, memberships = _repos(membership=None)

    with pytest.raises(NotFoundError):
        call(users, memberships)
    memberships.update.assert_not_called()


def test_update_user_role_invalid_role():
    users, memberships = _repos(membership=_membership())

    handler = UpdateUserRoleCommandHandler(users, memberships)

    with pytest.raises(ValueError):
        handler.handle(UpdateUserRoleCommand(tenant_id=TENANT, user_id=1, role=99))


def test_deactivate_removes_the_user_from_the_tenant_only():
    user = _make_user()
    users, memberships = _repos(user=user, membership=_membership())
    session_repo = Mock()

    result = DeactivateUserCommandHandler(users, session_repo, memberships).handle(
        DeactivateUserCommand(tenant_id=TENANT, user_id=1)
    )

    assert result["is_active"] is False
    assert memberships.update.call_args.args[0].active is False
    assert user.is_active  # the account still works in its other tenants
    users.update.assert_not_called()
    call = session_repo.revoke_all_for_user.call_args
    assert call.args[0] == 1
    assert call.kwargs["tenant_id"] == TENANT


def test_activate_gives_back_access_to_the_tenant():
    users, memberships = _repos(membership=_membership(active=False))

    result = ActivateUserCommandHandler(users, memberships).handle(
        ActivateUserCommand(tenant_id=TENANT, user_id=1)
    )

    assert result["is_active"] is True
    assert memberships.update.call_args.args[0].active is True


def test_last_active_admin_of_the_tenant_cannot_be_deactivated():
    users, memberships = _repos(membership=_membership(role=Role.ADMIN), admins=1)

    with pytest.raises(LastAdminError):
        DeactivateUserCommandHandler(users, Mock(), memberships).handle(
            DeactivateUserCommand(tenant_id=TENANT, user_id=1)
        )
    memberships.lock_active_admins.assert_called_once_with(TENANT)
    memberships.update.assert_not_called()


def test_an_admin_can_be_deactivated_while_another_remains_in_the_tenant():
    users, memberships = _repos(membership=_membership(role=Role.ADMIN), admins=2)

    result = DeactivateUserCommandHandler(users, Mock(), memberships).handle(
        DeactivateUserCommand(tenant_id=TENANT, user_id=1)
    )

    assert result["is_active"] is False


def test_last_active_admin_cannot_lose_the_admin_role():
    users, memberships = _repos(membership=_membership(role=Role.ADMIN), admins=1)

    with pytest.raises(LastAdminError):
        UpdateUserRoleCommandHandler(users, memberships).handle(
            UpdateUserRoleCommand(tenant_id=TENANT, user_id=1, role=Role.MANAGER.value)
        )
    memberships.update.assert_not_called()


@pytest.mark.parametrize(
    "user, membership",
    [
        (_make_user(), _membership(role=Role.MANAGER)),
        (_make_user(), _membership(role=Role.ADMIN, active=False)),
        (_make_user(is_active=False), _membership(role=Role.ADMIN)),
    ],
    ids=["not-admin", "inactive-membership", "blocked-account"],
)
def test_only_an_active_admin_counts_for_the_last_admin_rule(user, membership):
    users, memberships = _repos(user=user, membership=membership, admins=1)

    DeactivateUserCommandHandler(users, Mock(), memberships).handle(
        DeactivateUserCommand(tenant_id=TENANT, user_id=1)
    )

    memberships.lock_active_admins.assert_not_called()
