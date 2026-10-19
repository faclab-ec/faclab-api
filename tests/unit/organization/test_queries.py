"""Unit tests for the organization query handlers."""

from unittest.mock import Mock

import pytest

from src.organization.app.queries.branch import (
    GetAccessibleBranchesQuery,
    GetAccessibleBranchesQueryHandler,
)
from src.organization.app.queries.pos_terminal import (
    GetAllPosTerminalsQuery,
    GetAllPosTerminalsQueryHandler,
    GetBranchTerminalsQuery,
    GetBranchTerminalsQueryHandler,
)
from src.organization.domain.entities import Branch, PosTerminal
from src.organization.domain.exceptions import BranchInactiveError
from src.shared.domain.exceptions import NotFoundError


def _terminal(id: int, code: str) -> PosTerminal:
    return PosTerminal(
        id=id,
        branch_id=1,
        emission_point_id=1,
        default_location_id=1,
        code=code,
        name=code,
    )


def _branches(*branches: Branch) -> Mock:
    repo = Mock()
    repo.get_by_id.return_value = branches[0] if branches else None
    repo.filter_by.return_value = list(branches)
    return repo


def test_the_branch_terminals_are_its_active_ones_by_code():
    terminals = Mock()
    terminals.filter_by.return_value = [
        _terminal(2, "CAJA-02"),
        _terminal(1, "CAJA-01"),
    ]
    handler = GetBranchTerminalsQueryHandler(
        terminals, _branches(Branch(id=1, establishment_code="001", name="Matriz"))
    )

    result = handler.handle(GetBranchTerminalsQuery(branch_id=1))

    assert [t["code"] for t in result] == ["CAJA-01", "CAJA-02"]
    terminals.filter_by.assert_called_once_with(branch_id=1, is_active=True)


def test_the_terminals_of_a_missing_branch_are_not_found():
    with pytest.raises(NotFoundError):
        GetBranchTerminalsQueryHandler(Mock(), _branches()).handle(
            GetBranchTerminalsQuery(branch_id=9)
        )


def test_an_inactive_branch_has_no_terminals_to_use():
    inactive = Branch(id=1, establishment_code="001", name="Matriz", is_active=False)

    with pytest.raises(BranchInactiveError):
        GetBranchTerminalsQueryHandler(Mock(), _branches(inactive)).handle(
            GetBranchTerminalsQuery(branch_id=1)
        )


def test_terminals_are_listed_by_branch():
    repo = Mock()
    repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }

    GetAllPosTerminalsQueryHandler(repo).handle(GetAllPosTerminalsQuery(branch_id=3))

    repo.paginate.assert_called_once_with(limit=None, offset=None, branch_id=3)


def test_the_accessible_branches_are_the_active_ones_the_user_may_enter():
    repo = _branches(
        Branch(id=3, establishment_code="003", name="Cuenca"),
        Branch(id=1, establishment_code="001", name="Quito", is_main=True),
        Branch(id=2, establishment_code="002", name="Guayaquil"),
    )
    handler = GetAccessibleBranchesQueryHandler(repo)

    every = handler.handle(GetAccessibleBranchesQuery())
    limited = handler.handle(GetAccessibleBranchesQuery(branch_ids=frozenset({3, 2})))

    assert [b["establishment_code"] for b in every] == ["001", "002", "003"]
    assert [b["id"] for b in limited] == [2, 3]
    repo.filter_by.assert_called_with(is_active=True)
