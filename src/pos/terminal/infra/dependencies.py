"""The POS headers: `X-Branch-Id` (checked against the user's branches by
`AuthMiddleware`) and `X-Terminal-Id`. faclab-web sends both since S2.9; a
request without them is rejected."""

import re

from fastapi import Depends, Header, Request

from src.auth.domain.entities import AuthenticatedUser
from src.auth.domain.exceptions import BranchRequiredError
from src.auth.infra.dependencies import get_current_user
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.domain.exceptions import (
    InvalidTerminalHeaderError,
    TerminalRequiredError,
)

# A positive id that fits the terminals' integer key
_TERMINAL_ID = re.compile(r"[1-9][0-9]{0,9}")
_MAX_ID = 2**31 - 1

_BRANCH_DESCRIPTION = (
    "Branch of the operation, one the user may enter (`BRANCH_ACCESS_DENIED`, 403)"
)


def pos_terminal(
    request: Request,
    # Authenticated first: a request without a token answers 401, not 400
    _user: AuthenticatedUser = Depends(get_current_user),
    branch: str | None = Header(
        None, alias="X-Branch-Id", description=_BRANCH_DESCRIPTION
    ),
    terminal: str | None = Header(
        None,
        alias="X-Terminal-Id",
        description="POS terminal of the operation, one of the branch in X-Branch-Id",
    ),
) -> TerminalRequest:
    """The terminal a POS operation starts at (`TERMINAL_REQUIRED` without it)"""
    if terminal is None:
        raise TerminalRequiredError()
    value = terminal.strip()
    if not _TERMINAL_ID.fullmatch(value) or int(value) > _MAX_ID:
        raise InvalidTerminalHeaderError()
    return TerminalRequest(
        branch_id=_branch_id(request, branch), terminal_id=int(value)
    )


def pos_branch(
    request: Request,
    _user: AuthenticatedUser = Depends(get_current_user),
    branch: str | None = Header(
        None, alias="X-Branch-Id", description=_BRANCH_DESCRIPTION
    ),
) -> TerminalRequest:
    """The branch of a POS operation on an existing sale, shift or refund
    (`BRANCH_REQUIRED` without it)"""
    return TerminalRequest(branch_id=_branch_id(request, branch))


def _branch_id(request: Request, header: str | None) -> int:
    """The branch `AuthMiddleware` read from `X-Branch-Id` (`BRANCH_REQUIRED`
    without it)"""
    branch_id = getattr(request.state, "branch_id", None)
    if header is None or branch_id is None:
        raise BranchRequiredError()
    return branch_id
