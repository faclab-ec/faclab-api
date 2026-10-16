from unittest.mock import Mock
from uuid import UUID

import pytest

from src.auth.app.commands.create_user import (
    CreateUserCommand,
    CreateUserCommandHandler,
)
from src.auth.app.commands.update_user_profile import (
    UpdateUserProfileCommand,
    UpdateUserProfileCommandHandler,
)
from src.auth.domain.entities import AuthenticatedUser, Role, User
from src.auth.domain.events import UserCreated
from src.auth.domain.exceptions import UserInOtherTenantsError
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.domain.entities import Membership

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _user(**overrides) -> User:
    return User(id=1, username="ana", email="ana@x.ec", password_hash="h", **overrides)


def _memberships(membership=None, elsewhere=False):
    memberships = Mock()
    memberships.get_for.return_value = membership or Membership(
        tenant_id=TENANT, user_id=1, role=Role.CASHIER, id=3
    )
    memberships.has_active_elsewhere.return_value = elsewhere
    return memberships


def test_update_profile_sets_and_clears_the_full_name():
    user = _user()
    repo = Mock()
    repo.get_by_id.return_value = user
    repo.update.side_effect = lambda u: u
    handler = UpdateUserProfileCommandHandler(repo, _memberships())

    result = handler.handle(
        UpdateUserProfileCommand(tenant_id=TENANT, user_id=1, full_name="Ana Pérez")
    )
    assert result["full_name"] == "Ana Pérez"
    assert result["role"] == Role.CASHIER

    result = handler.handle(
        UpdateUserProfileCommand(tenant_id=TENANT, user_id=1, full_name="")
    )
    assert result["full_name"] is None


def test_update_profile_of_a_user_outside_the_tenant_raises_not_found():
    repo = Mock()
    memberships = Mock()
    memberships.get_for.return_value = None

    with pytest.raises(NotFoundError):
        UpdateUserProfileCommandHandler(repo, memberships).handle(
            UpdateUserProfileCommand(tenant_id=TENANT, user_id=9, full_name="X")
        )
    repo.update.assert_not_called()


def test_the_name_of_a_user_who_also_works_elsewhere_cannot_change_here():
    repo = Mock()
    repo.get_by_id.return_value = _user()
    memberships = _memberships(elsewhere=True)

    with pytest.raises(UserInOtherTenantsError) as exc:
        UpdateUserProfileCommandHandler(repo, memberships).handle(
            UpdateUserProfileCommand(tenant_id=TENANT, user_id=1, full_name="X")
        )

    assert exc.value.error_code == "USER_IN_OTHER_TENANTS"
    memberships.has_active_elsewhere.assert_called_once_with(1, TENANT)
    repo.update.assert_not_called()


def _saved(user: User) -> User:
    user.id = 5
    return user


def _create(**overrides) -> tuple[dict, Mock, Mock]:
    repo = Mock()
    repo.get_by_username.return_value = None
    repo.get_by_email.return_value = None
    repo.create.side_effect = _saved
    memberships = Mock()
    memberships.create.side_effect = lambda m: m
    hasher = Mock()
    hasher.hash.return_value = "hashed"
    publisher = Mock()
    command = CreateUserCommand(
        tenant_id=TENANT,
        username="ana",
        email="ana@x.ec",
        password="Secret123",
        **overrides,
    )
    result = CreateUserCommandHandler(repo, memberships, hasher, publisher).handle(
        command
    )
    return result, memberships, publisher


def test_create_user_stores_the_full_name():
    result, *_ = _create(full_name=" Ana Pérez ")

    assert result["full_name"] == "Ana Pérez"


def test_create_user_adds_it_to_the_tenant_with_the_role():
    result, memberships, publisher = _create(role=Role.CASHIER.value)

    [membership] = memberships.create.call_args.args
    assert (membership.tenant_id, membership.user_id) == (TENANT, 5)
    assert (membership.role, membership.active) == (Role.CASHIER, True)
    assert (result["role"], result["is_active"]) == (Role.CASHIER, True)
    event = publisher.publish.call_args.args[0]
    assert isinstance(event, UserCreated)
    assert (event.tenant_id, event.role) == (TENANT, Role.CASHIER.value)


def test_the_authenticated_user_signs_with_the_full_name_or_the_username():
    assert (
        AuthenticatedUser(
            id=1, username="ana", role=Role.CASHIER, tenant_id=TENANT
        ).display_name
        == "ana"
    )
    assert (
        AuthenticatedUser(
            id=1,
            username="ana",
            role=Role.CASHIER,
            tenant_id=TENANT,
            full_name="Ana Pérez",
        ).display_name
        == "Ana Pérez"
    )
