from dataclasses import dataclass

from wireup import injectable

from src.auth.domain.exceptions import BranchAccessDeniedError, BranchRequiredError
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
    """Where a POS request runs: `X-Branch-Id` and `X-Terminal-Id`.

    None asks for the local fallback (`POS_TERMINAL_FALLBACK`, until the web
    sends the headers in S2.9): the header's branch or else the main one, and
    its first active terminal by code."""

    branch_id: int | None = None
    terminal_id: int | None = None
    # The user's branches (claim `bids`; None: all). The headers were already
    # checked against them; the fallback checks the branch it picks.
    allowed_branches: frozenset[int] | None = None


@injectable(lifetime="scoped")
class TerminalResolver:
    """The terminal or the branch of a POS request"""

    def __init__(self, terminals: PosTerminalRepository, branches: BranchRepository):
        self.terminals = terminals
        self.branches = branches

    def terminal(self, request: TerminalRequest) -> PosTerminal:
        """An active terminal of an active branch, the one of the request"""
        if request.terminal_id is None:
            return self._fallback_terminal(request)
        if request.branch_id is None:
            raise BranchRequiredError()
        terminal = self.terminals.get_by_id(request.terminal_id)
        if terminal is None:
            raise NotFoundError(f"POS terminal {request.terminal_id} not found")
        if terminal.branch_id != request.branch_id:
            raise PosTerminalOutsideBranchError()
        self._active_branch(terminal.branch_id)
        if not terminal.is_active:
            raise PosTerminalInactiveError(terminal.require_id())
        return terminal

    def branch_id(self, request: TerminalRequest) -> int:
        """The branch the request operates in. Not checked against the
        database: a branch that doesn't exist has no sales or shifts to find."""
        if request.branch_id is not None:
            return request.branch_id
        return self._main_branch(request).require_id()

    def _fallback_terminal(self, request: TerminalRequest) -> PosTerminal:
        if request.branch_id is not None:
            branch = self._active_branch(request.branch_id)
        else:
            branch = self._main_branch(request)
            if not branch.is_active:
                raise BranchInactiveError(branch.require_id())
        terminals = self.terminals.filter_by(branch_id=branch.id, is_active=True)
        if not terminals:
            raise TerminalRequiredError(
                "the branch has no active POS terminal: send X-Terminal-Id"
            )
        return min(terminals, key=lambda t: t.code)

    def _main_branch(self, request: TerminalRequest) -> Branch:
        branch = self.branches.first(is_main=True)
        if branch is None:
            raise BranchRequiredError()
        allowed = request.allowed_branches
        if allowed is not None and branch.id not in allowed:
            raise BranchAccessDeniedError()
        return branch

    def _active_branch(self, branch_id: int) -> Branch:
        branch = self.branches.get_by_id(branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {branch_id} not found")
        if not branch.is_active:
            raise BranchInactiveError(branch_id)
        return branch
