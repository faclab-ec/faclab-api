from unittest.mock import MagicMock

import pytest

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
    branch_repo = MagicMock()
    branch_repo.get_by_id.side_effect = lambda id: next(
        (b for b in branches if b.id == id), None
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


def test_an_operation_at_a_terminal_needs_one():
    with pytest.raises(TerminalRequiredError):
        _resolver([_terminal(3)]).terminal(TerminalRequest(branch_id=1))
