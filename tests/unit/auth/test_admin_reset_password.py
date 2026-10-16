from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from src.auth.app.commands.admin_reset_password import (
    AdminResetPasswordCommand,
    AdminResetPasswordCommandHandler,
)
from src.auth.domain.entities import Role, User
from src.auth.domain.events import UserPasswordReset
from src.auth.domain.exceptions import UserInOtherTenantsError
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.domain.entities import Membership

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _user(**overrides):
    defaults: dict[str, Any] = {
        "id": 7,
        "username": "cashier01",
        "email": "c01@example.com",
        "password_hash": "old_hash",
    }
    defaults.update(overrides)
    return User(**defaults)


def _memberships(found=True, elsewhere=False):
    memberships = Mock()
    memberships.get_for.return_value = (
        Membership(tenant_id=TENANT, user_id=7, role=Role.CASHIER, id=2)
        if found
        else None
    )
    memberships.has_active_elsewhere.return_value = elsewhere
    return memberships


def test_admin_reset_password_sets_flag_and_rehashes():
    user = _user()
    repo = Mock()
    repo.get_by_id.return_value = user
    repo.update.side_effect = lambda u: u

    hasher = Mock()
    hasher.hash.return_value = "new_hash"

    publisher = MagicMock()

    session_repo = MagicMock()
    handler = AdminResetPasswordCommandHandler(
        repo, session_repo, _memberships(), hasher, publisher
    )
    result = handler.handle(
        AdminResetPasswordCommand(
            tenant_id=TENANT,
            user_id=7,
            new_password="TempPass123",
            reset_by_user_id=1,
        )
    )

    hasher.hash.assert_called_once_with("TempPass123")
    updated = repo.update.call_args[0][0]
    assert updated.password_hash == "new_hash"
    assert updated.must_change_password is True
    assert result["must_change_password"] is True
    # The password works in every tenant, so every session ends
    assert session_repo.revoke_all_for_user.call_args.kwargs == {}

    publisher.publish.assert_called_once()
    event = publisher.publish.call_args[0][0]
    assert isinstance(event, UserPasswordReset)
    assert event.user_id == 7
    assert event.reset_by_user_id == 1


def test_admin_reset_password_of_a_user_outside_the_tenant_is_not_found():
    repo = Mock()

    handler = AdminResetPasswordCommandHandler(
        repo, MagicMock(), _memberships(found=False), Mock(), MagicMock()
    )

    with pytest.raises(NotFoundError):
        handler.handle(
            AdminResetPasswordCommand(
                tenant_id=TENANT,
                user_id=999,
                new_password="TempPass123",
                reset_by_user_id=1,
            )
        )


def test_the_password_of_a_user_who_also_works_elsewhere_cannot_be_reset():
    repo = Mock()
    repo.get_by_id.return_value = _user()
    hasher = Mock()

    handler = AdminResetPasswordCommandHandler(
        repo, MagicMock(), _memberships(elsewhere=True), hasher, MagicMock()
    )

    with pytest.raises(UserInOtherTenantsError):
        handler.handle(
            AdminResetPasswordCommand(
                tenant_id=TENANT,
                user_id=7,
                new_password="TempPass123",
                reset_by_user_id=1,
            )
        )
    hasher.hash.assert_not_called()
    repo.update.assert_not_called()


def test_admin_reset_password_rejects_weak_password():
    repo = Mock()
    repo.get_by_id.return_value = _user()

    handler = AdminResetPasswordCommandHandler(
        repo, MagicMock(), _memberships(), Mock(), MagicMock()
    )

    with pytest.raises(ValueError):
        handler.handle(
            AdminResetPasswordCommand(
                tenant_id=TENANT,
                user_id=7,
                new_password="short",
                reset_by_user_id=1,
            )
        )


def test_change_password_clears_must_change_flag():
    from src.auth.app.commands.change_password import (
        ChangePasswordCommand,
        ChangePasswordCommandHandler,
    )

    user = _user(must_change_password=True)
    repo = Mock()
    repo.get_by_id.return_value = user
    repo.update.side_effect = lambda u: u

    hasher = Mock()
    hasher.verify.return_value = True
    hasher.hash.return_value = "brand_new"

    handler = ChangePasswordCommandHandler(repo, MagicMock(), hasher, MagicMock())
    handler.handle(
        ChangePasswordCommand(
            user_id=7,
            current_password="TempPass123",
            new_password="LongerPass456",
        )
    )

    updated = repo.update.call_args[0][0]
    assert updated.must_change_password is False
    assert updated.password_hash == "brand_new"
