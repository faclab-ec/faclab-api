from unittest.mock import Mock

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
from src.shared.domain.exceptions import NotFoundError


def _user(**overrides) -> User:
    return User(id=1, username="ana", email="ana@x.ec", password_hash="h", **overrides)


def test_update_profile_sets_and_clears_the_full_name():
    user = _user()
    repo = Mock()
    repo.get_by_id.return_value = user
    repo.update.side_effect = lambda u: u
    handler = UpdateUserProfileCommandHandler(repo)

    result = handler.handle(UpdateUserProfileCommand(user_id=1, full_name="Ana Pérez"))
    assert result["full_name"] == "Ana Pérez"

    result = handler.handle(UpdateUserProfileCommand(user_id=1, full_name=""))
    assert result["full_name"] is None


def test_update_profile_of_a_missing_user_raises_not_found():
    repo = Mock()
    repo.get_by_id.return_value = None

    with pytest.raises(NotFoundError):
        UpdateUserProfileCommandHandler(repo).handle(
            UpdateUserProfileCommand(user_id=9, full_name="X")
        )


def _saved(user: User) -> User:
    user.id = 5
    return user


def test_create_user_stores_the_full_name():
    repo = Mock()
    repo.get_by_username.return_value = None
    repo.get_by_email.return_value = None
    repo.create.side_effect = _saved
    hasher = Mock()
    hasher.hash.return_value = "hashed"

    result = CreateUserCommandHandler(repo, hasher, Mock()).handle(
        CreateUserCommand(
            username="ana",
            email="ana@x.ec",
            password="Secret123",
            full_name=" Ana Pérez ",
        )
    )

    assert result["full_name"] == "Ana Pérez"


def test_the_authenticated_user_signs_with_the_full_name_or_the_username():
    assert (
        AuthenticatedUser(id=1, username="ana", role=Role.CASHIER).display_name == "ana"
    )
    assert (
        AuthenticatedUser(
            id=1, username="ana", role=Role.CASHIER, full_name="Ana Pérez"
        ).display_name
        == "Ana Pérez"
    )
