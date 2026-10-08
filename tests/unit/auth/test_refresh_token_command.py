from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.refresh_token import (
    RefreshTokenCommand,
    RefreshTokenCommandHandler,
)
from src.auth.app.services.token_service import TokenClaims, TokenPair
from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import InvalidTokenError


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "h",
        "role": Role.ADMIN,
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _claims() -> TokenClaims:
    return TokenClaims(
        sub=1,
        username="alice",
        role=1,
        typ="refresh",
        iat=0,
        exp=0,
        iss="faclab",
    )


def test_refresh_valid_returns_new_pair():
    repo = MagicMock()
    repo.get_by_id.return_value = _user()
    token_service = MagicMock()
    token_service.decode_refresh.return_value = _claims()
    token_service.issue_pair.return_value = TokenPair(
        access_token="a2", refresh_token="r2", expires_in=900
    )

    handler = RefreshTokenCommandHandler(repo, token_service)
    result = handler.handle(RefreshTokenCommand(refresh_token="old"))

    assert result.access_token == "a2"
    token_service.decode_refresh.assert_called_once_with("old")
    token_service.issue_pair.assert_called_once()


def test_refresh_inactive_user_raises_invalid_token():
    repo = MagicMock()
    repo.get_by_id.return_value = _user(is_active=False)
    token_service = MagicMock()
    token_service.decode_refresh.return_value = _claims()

    handler = RefreshTokenCommandHandler(repo, token_service)
    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))


def test_refresh_unknown_user_raises_invalid_token():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    token_service = MagicMock()
    token_service.decode_refresh.return_value = _claims()

    handler = RefreshTokenCommandHandler(repo, token_service)
    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))


def test_refresh_propagates_invalid_token_from_service():
    repo = MagicMock()
    token_service = MagicMock()
    token_service.decode_refresh.side_effect = InvalidTokenError("bad typ")

    handler = RefreshTokenCommandHandler(repo, token_service)
    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="access-token"))
    repo.get_by_id.assert_not_called()
