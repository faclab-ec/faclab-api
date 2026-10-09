from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from src.auth.app.commands.change_password import (
    ChangePasswordCommand,
    ChangePasswordCommandHandler,
)
from src.auth.domain.entities import Role, User
from src.auth.domain.events import UserPasswordChanged
from src.auth.domain.exceptions import InvalidCredentialsError
from src.shared.domain.exceptions import NotFoundError


def _make_user(**overrides):
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hashed_old",
        "role": Role.ADMIN,
    }
    defaults.update(overrides)
    return User(**defaults)


def test_change_password_success():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user
    mock_repo.update.return_value = user

    mock_hasher = Mock()
    mock_hasher.verify.return_value = True
    mock_hasher.hash.return_value = "hashed_new"

    event_publisher = MagicMock()

    handler = ChangePasswordCommandHandler(
        mock_repo, MagicMock(), mock_hasher, event_publisher
    )
    handler.handle(
        ChangePasswordCommand(
            user_id=1,
            current_password="oldpass12",
            new_password="newpass12",
        )
    )

    mock_hasher.verify.assert_called_once_with("oldpass12", "hashed_old")
    mock_hasher.hash.assert_called_once_with("newpass12")
    mock_repo.update.assert_called_once()
    updated_user = mock_repo.update.call_args[0][0]
    assert updated_user.password_hash == "hashed_new"

    event_publisher.publish.assert_called_once()
    event = event_publisher.publish.call_args[0][0]
    assert isinstance(event, UserPasswordChanged)
    assert event.user_id == 1


def test_change_password_wrong_current_raises_invalid_credentials():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user

    mock_hasher = Mock()
    mock_hasher.verify.return_value = False

    handler = ChangePasswordCommandHandler(
        mock_repo, MagicMock(), mock_hasher, MagicMock()
    )

    with pytest.raises(InvalidCredentialsError):
        handler.handle(
            ChangePasswordCommand(
                user_id=1,
                current_password="wrongpass",
                new_password="newpass12",
            )
        )


def test_change_password_user_not_found():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = ChangePasswordCommandHandler(mock_repo, MagicMock(), Mock(), MagicMock())

    with pytest.raises(NotFoundError):
        handler.handle(
            ChangePasswordCommand(
                user_id=999,
                current_password="old",
                new_password="newpass12",
            )
        )


def test_change_password_weak_new_password():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user

    handler = ChangePasswordCommandHandler(mock_repo, MagicMock(), Mock(), MagicMock())

    with pytest.raises(ValueError):
        handler.handle(
            ChangePasswordCommand(
                user_id=1,
                current_password="oldpass12",
                new_password="short",
            )
        )


def test_change_password_closes_every_other_session():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = _make_user()
    mock_hasher = Mock()
    mock_hasher.verify.return_value = True
    mock_hasher.hash.return_value = "hashed_new"
    session_repo = MagicMock()

    ChangePasswordCommandHandler(
        mock_repo, session_repo, mock_hasher, MagicMock()
    ).handle(
        ChangePasswordCommand(
            user_id=1,
            current_password="oldpass12",
            new_password="newpass12",
            keep_session_id=5,
        )
    )

    user_id, _now, keep = session_repo.revoke_all_for_user.call_args.args
    assert (user_id, keep) == (1, 5)
