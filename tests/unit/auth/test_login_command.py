from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.login import LoginCommand, LoginCommandHandler
from src.auth.app.services.token_service import TokenPair
from src.auth.domain.entities import AuthSession, Role, User
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
    session_repo = MagicMock()
    session_repo.create.side_effect = lambda session: AuthSession(
        id=42, user_id=session.user_id, expires_at=session.expires_at
    )
    token_service = MagicMock()
    token_service.refresh_ttl_seconds = 604800
    token_service.issue_pair.return_value = TokenPair(
        access_token="a", refresh_token="r", expires_in=900
    )
    publisher = MagicMock()
    handler = LoginCommandHandler(repo, session_repo, hasher, token_service, publisher)
    return handler, repo, publisher, session_repo, token_service


def test_login_with_valid_credentials_returns_pair_and_updates_last_login():
    handler, repo, publisher, *_ = _handler(user=_user())
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


def test_login_opens_a_session_that_lasts_as_long_as_the_refresh_token():
    handler, _, _, session_repo, token_service = _handler(user=_user())

    handler.handle(LoginCommand(username="alice", password="pw"))

    [session] = session_repo.create.call_args.args
    assert session.user_id == 1
    assert (session.expires_at - datetime.now()).days == 6  # 7 days minus a moment
    user, session_id = token_service.issue_pair.call_args.args
    assert (user.id, session_id) == (1, 42)
