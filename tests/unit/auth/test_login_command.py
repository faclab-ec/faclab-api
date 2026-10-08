from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.login import LoginCommand, LoginCommandHandler
from src.auth.app.services.token_service import TokenPair
from src.auth.domain.entities import Role, User
from src.auth.domain.events import UserLoggedIn
from src.auth.domain.exceptions import InvalidCredentialsError


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "hashed",
        "role": Role.ADMIN,
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _handler(user=None, verify=True):
    repo = MagicMock()
    repo.get_by_username.return_value = user
    repo.update.side_effect = lambda u: u
    hasher = MagicMock()
    hasher.verify.return_value = verify
    token_service = MagicMock()
    token_service.issue_pair.return_value = TokenPair(
        access_token="a", refresh_token="r", expires_in=900
    )
    publisher = MagicMock()
    return LoginCommandHandler(repo, hasher, token_service, publisher), repo, publisher


def test_login_with_valid_credentials_returns_pair_and_updates_last_login():
    handler, repo, publisher = _handler(user=_user())
    result = handler.handle(LoginCommand(username="alice", password="pw"))

    assert result.access_token == "a"
    assert result.refresh_token == "r"
    repo.update.assert_called_once()
    updated = repo.update.call_args[0][0]
    assert updated.last_login_at is not None

    publisher.publish.assert_called_once()
    event = publisher.publish.call_args[0][0]
    assert isinstance(event, UserLoggedIn)
    assert event.user_id == 1
    assert event.username == "alice"


def test_login_unknown_user_raises_invalid_credentials():
    handler, *_ = _handler(user=None)
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="ghost", password="pw"))


def test_login_inactive_user_raises_invalid_credentials():
    handler, *_ = _handler(user=_user(is_active=False))
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="alice", password="pw"))


def test_login_wrong_password_raises_invalid_credentials():
    handler, *_ = _handler(user=_user(), verify=False)
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="alice", password="bad"))
