from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest

from src.auth.app.queries.get_users import (
    GetUserByIdQuery,
    GetUserByIdQueryHandler,
    ListUsersQuery,
    ListUsersQueryHandler,
)
from src.auth.app.types import TenantMember
from src.auth.domain.entities import Role, User
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.domain.entities import Membership

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _make_user(**overrides):
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hashed",
    }
    defaults.update(overrides)
    return User(**defaults)


def test_list_users_lists_the_members_of_the_tenant():
    mock_repo = Mock()
    mock_repo.paginate_members.return_value = {
        "total": 1,
        "limit": 100,
        "offset": 0,
        "items": [{"id": 1}],
    }

    handler = ListUsersQueryHandler(mock_repo)
    result = handler.handle(ListUsersQuery(tenant_id=TENANT))

    assert result["total"] == 1
    assert len(result["items"]) == 1
    mock_repo.paginate_members.assert_called_once_with(
        TENANT, role=None, is_active=None, limit=None, offset=None
    )


def test_list_users_passes_filters():
    mock_repo = Mock()
    mock_repo.paginate_members.return_value = {
        "total": 0,
        "limit": 10,
        "offset": 0,
        "items": [],
    }

    handler = ListUsersQueryHandler(mock_repo)
    handler.handle(
        ListUsersQuery(tenant_id=TENANT, is_active=True, role=1, limit=10, offset=0)
    )

    mock_repo.paginate_members.assert_called_once_with(
        TENANT, role=Role.ADMIN, is_active=True, limit=10, offset=0
    )


def test_get_user_by_id_shows_the_membership_role_and_state():
    membership = Membership(
        tenant_id=TENANT, user_id=1, role=Role.CASHIER, active=False, id=4
    )
    mock_repo = Mock()
    mock_repo.get_member.return_value = TenantMember(_make_user(), membership)

    handler = GetUserByIdQueryHandler(mock_repo)
    result = handler.handle(GetUserByIdQuery(tenant_id=TENANT, user_id=1))

    assert result["id"] == 1
    assert result["username"] == "testuser"
    assert result["role"] == Role.CASHIER
    assert result["is_active"] is False
    mock_repo.get_member.assert_called_once_with(TENANT, 1)


def test_a_user_outside_the_tenant_is_not_found():
    mock_repo = Mock()
    mock_repo.get_member.return_value = None

    handler = GetUserByIdQueryHandler(mock_repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetUserByIdQuery(tenant_id=TENANT, user_id=999))
