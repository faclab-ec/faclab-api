from dataclasses import dataclass

from wireup import injectable

from src.organization.app.repositories import BranchRepository, PosTerminalRepository
from src.organization.domain.entities import Branch, PosTerminal
from src.organization.domain.exceptions import BranchInactiveError
from src.pos.terminal.domain.exceptions import (
    PosTerminalInactiveError,
    PosTerminalOutsideBranchError,
    TerminalRequiredError,
)
from src.shared.domain.exceptions import NotFoundError


@dataclass(frozen=True)
class TerminalRequest:
    """Where a POS request runs: `X-Branch-Id` and, for an operation that
    starts at a terminal, `X-Terminal-Id`. `AuthMiddleware` already checked
    the branch against the user's."""

    branch_id: int
    terminal_id: int | None = None


@injectable(lifetime="scoped")
class TerminalResolver:
    """The terminal of a POS request"""

    def __init__(self, terminals: PosTerminalRepository, branches: BranchRepository):
        self.terminals = terminals
        self.branches = branches

    def terminal(self, request: TerminalRequest) -> PosTerminal:
        """An active terminal of an active branch, the one of the request"""
        if request.terminal_id is None:
            raise TerminalRequiredError()
        terminal = self.terminals.get_by_id(request.terminal_id)
        if terminal is None:
            raise NotFoundError(f"POS terminal {request.terminal_id} not found")
        if terminal.branch_id != request.branch_id:
            raise PosTerminalOutsideBranchError()
        self._active_branch(terminal.branch_id)
        if not terminal.is_active:
            raise PosTerminalInactiveError(terminal.require_id())
        return terminal

    def _active_branch(self, branch_id: int) -> Branch:
        branch = self.branches.get_by_id(branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {branch_id} not found")
        if not branch.is_active:
            raise BranchInactiveError(branch_id)
        return branch
