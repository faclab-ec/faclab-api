from typing import Any
from unittest.mock import Mock

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
from src.shared.domain.exceptions import NotFoundError


def _make_user(**overrides):
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hashed",
        "role": Role.VIEWER,
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def test_update_user_role_success():
    user = _make_user(role=Role.VIEWER)
    updated = _make_user(role=Role.MANAGER)
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user
    mock_repo.update.return_value = updated

    handler = UpdateUserRoleCommandHandler(mock_repo)
    result = handler.handle(UpdateUserRoleCommand(user_id=1, role=Role.MANAGER.value))

    assert result["role"] == Role.MANAGER
    mock_repo.update.assert_called_once()


def test_update_user_role_not_found():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = UpdateUserRoleCommandHandler(mock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateUserRoleCommand(user_id=999, role=Role.ADMIN.value))


def test_update_user_role_invalid_role():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user

    handler = UpdateUserRoleCommandHandler(mock_repo)

    with pytest.raises(ValueError):
        handler.handle(UpdateUserRoleCommand(user_id=1, role=99))


def test_deactivate_user_success():
    user = _make_user(is_active=True)
    deactivated = _make_user(is_active=False)
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user
    mock_repo.update.return_value = deactivated

    handler = DeactivateUserCommandHandler(mock_repo)
    result = handler.handle(DeactivateUserCommand(user_id=1))

    assert result["is_active"] is False
    updated_arg = mock_repo.update.call_args[0][0]
    assert updated_arg.is_active is False


def test_deactivate_user_not_found():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = DeactivateUserCommandHandler(mock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeactivateUserCommand(user_id=999))


def test_activate_user_success():
    user = _make_user(is_active=False)
    activated = _make_user(is_active=True)
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user
    mock_repo.update.return_value = activated

    handler = ActivateUserCommandHandler(mock_repo)
    result = handler.handle(ActivateUserCommand(user_id=1))

    assert result["is_active"] is True
    updated_arg = mock_repo.update.call_args[0][0]
    assert updated_arg.is_active is True


def test_activate_user_not_found():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = ActivateUserCommandHandler(mock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(ActivateUserCommand(user_id=999))
