from typing import Any
from unittest.mock import Mock

import pytest

from src.auth.app.queries.get_users import (
    GetUserByIdQuery,
    GetUserByIdQueryHandler,
    ListUsersQuery,
    ListUsersQueryHandler,
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
    }
    defaults.update(overrides)
    return User(**defaults)


def test_list_users_returns_paginated_result():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.paginate.return_value = {
        "total": 1,
        "limit": 100,
        "offset": 0,
        "items": [user.dict()],
    }

    handler = ListUsersQueryHandler(mock_repo)
    result = handler.handle(ListUsersQuery())

    assert result["total"] == 1
    assert len(result["items"]) == 1
    mock_repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_list_users_passes_filters():
    mock_repo = Mock()
    mock_repo.paginate.return_value = {
        "total": 0,
        "limit": 10,
        "offset": 0,
        "items": [],
    }

    handler = ListUsersQueryHandler(mock_repo)
    handler.handle(ListUsersQuery(is_active=True, role=1, limit=10, offset=0))

    mock_repo.paginate.assert_called_once_with(
        limit=10, offset=0, is_active=True, role=1
    )


def test_get_user_by_id_success():
    user = _make_user()
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = user

    handler = GetUserByIdQueryHandler(mock_repo)
    result = handler.handle(GetUserByIdQuery(user_id=1))

    assert result["id"] == 1
    assert result["username"] == "testuser"


def test_get_user_by_id_not_found():
    mock_repo = Mock()
    mock_repo.get_by_id.return_value = None

    handler = GetUserByIdQueryHandler(mock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetUserByIdQuery(user_id=999))
