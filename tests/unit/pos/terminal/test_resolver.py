from unittest.mock import MagicMock

import pytest

from src.auth.domain.exceptions import BranchAccessDeniedError
from src.organization.domain.entities import Branch, PosTerminal
from src.organization.domain.exceptions import BranchInactiveError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.pos.terminal.domain.exceptions import (
    PosTerminalInactiveError,
    PosTerminalOutsideBranchError,
    TerminalRequiredError,
)
from src.shared.domain.exceptions import NotFoundError

MAIN = Branch(id=1, establishment_code="001", name="Matriz", is_main=True)
NORTH = Branch(id=2, establishment_code="002", name="Norte")


def _terminal(id: int, branch_id: int = 1, code: str = "CAJA-01", **kw) -> PosTerminal:
    return PosTerminal(
        id=id,
        branch_id=branch_id,
        emission_point_id=1,
        default_location_id=1,
        code=code,
        name=code,
        **kw,
    )


def _resolver(terminals=(), branches=(MAIN, NORTH)) -> TerminalResolver:
    terminal_repo = MagicMock()
    terminal_repo.get_by_id.side_effect = lambda id: next(
        (t for t in terminals if t.id == id), None
    )
    terminal_repo.filter_by.side_effect = lambda branch_id, is_active: [
        t for t in terminals if t.branch_id == branch_id and t.is_active == is_active
    ]
    branch_repo = MagicMock()
    branch_repo.get_by_id.side_effect = lambda id: next(
        (b for b in branches if b.id == id), None
    )
    branch_repo.first.side_effect = lambda is_main: next(
        (b for b in branches if b.is_main == is_main), None
    )
    return TerminalResolver(terminal_repo, branch_repo)


def test_the_terminal_of_the_headers():
    terminal = _terminal(3)

    found = _resolver([terminal]).terminal(TerminalRequest(1, 3))

    assert found == terminal


def test_a_terminal_that_doesnt_exist():
    with pytest.raises(NotFoundError):
        _resolver().terminal(TerminalRequest(1, 3))


def test_a_terminal_of_another_branch():
    resolver = _resolver([_terminal(3, branch_id=2)])

    with pytest.raises(PosTerminalOutsideBranchError):
        resolver.terminal(TerminalRequest(1, 3))


def test_an_inactive_terminal_or_branch():
    inactive = _resolver([_terminal(3, is_active=False)])
    closed_branch = _resolver(
        [_terminal(3)],
        branches=(
            Branch(id=1, establishment_code="001", name="Matriz", is_active=False),
        ),
    )

    with pytest.raises(PosTerminalInactiveError):
        inactive.terminal(TerminalRequest(1, 3))
    with pytest.raises(BranchInactiveError):
        closed_branch.terminal(TerminalRequest(1, 3))


def test_the_fallback_takes_the_first_active_terminal_of_the_main_branch():
    resolver = _resolver(
        [
            _terminal(4, code="CAJA-02"),
            _terminal(5, code="CAJA-00", is_active=False),
            _terminal(3, code="CAJA-01"),
            _terminal(6, branch_id=2, code="CAJA-00"),
        ]
    )

    assert resolver.terminal(TerminalRequest()).id == 3
    assert resolver.branch_id(TerminalRequest()) == 1


def test_the_fallback_uses_the_branch_of_the_header():
    resolver = _resolver([_terminal(3), _terminal(6, branch_id=2, code="CAJA-09")])

    assert resolver.terminal(TerminalRequest(branch_id=2)).id == 6
    assert resolver.branch_id(TerminalRequest(branch_id=2)) == 2


def test_the_fallback_respects_the_users_branches():
    resolver = _resolver([_terminal(3)])
    limited = TerminalRequest(allowed_branches=frozenset({2}))

    with pytest.raises(BranchAccessDeniedError):
        resolver.terminal(limited)
    with pytest.raises(BranchAccessDeniedError):
        resolver.branch_id(limited)


def test_the_fallback_needs_an_active_terminal():
    with pytest.raises(TerminalRequiredError):
        _resolver([_terminal(3, is_active=False)]).terminal(TerminalRequest())
