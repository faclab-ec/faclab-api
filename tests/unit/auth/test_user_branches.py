"""Administration of the branches a user may enter (S2.5)"""

from unittest.mock import Mock
from uuid import UUID

import pytest

from src.auth.app.commands.set_user_branches import (
    SetUserBranchesCommand,
    SetUserBranchesCommandHandler,
)
from src.auth.app.queries.get_user_branches import (
    GetUserBranchesQuery,
    GetUserBranchesQueryHandler,
)
from src.auth.domain.entities import Role
from src.shared.domain.exceptions import NotFoundError
from src.tenancy.domain.entities import Membership

TENANT = UUID("11111111-1111-4111-8111-111111111111")


def _memberships(membership: Membership | None, branch_ids=()) -> Mock:
    memberships = Mock()
    memberships.get_for.return_value = membership
    memberships.branch_ids.return_value = list(branch_ids)
    return memberships


def _membership() -> Membership:
    return Membership(tenant_id=TENANT, user_id=2, role=Role.CASHIER, id=8)


def test_setting_the_branches_replaces_them_on_the_locked_membership():
    membership = _membership()
    memberships = _memberships(membership, branch_ids=[1, 3])

    result = SetUserBranchesCommandHandler(memberships).handle(
        SetUserBranchesCommand(tenant_id=TENANT, user_id=2, branch_ids=[3, 1])
    )

    memberships.get_for.assert_called_once_with(TENANT, 2, for_update=True)
    memberships.set_branches.assert_called_once_with(membership, [3, 1])
    assert result == {"user_id": 2, "branch_ids": [1, 3]}


def test_a_user_of_another_tenant_is_not_found():
    memberships = _memberships(None)

    with pytest.raises(NotFoundError):
        SetUserBranchesCommandHandler(memberships).handle(
            SetUserBranchesCommand(tenant_id=TENANT, user_id=2, branch_ids=[1])
        )
    memberships.set_branches.assert_not_called()


def test_no_branches_means_all_of_them():
    memberships = _memberships(_membership())

    result = GetUserBranchesQueryHandler(memberships).handle(
        GetUserBranchesQuery(tenant_id=TENANT, user_id=2)
    )

    assert result == {"user_id": 2, "branch_ids": []}
