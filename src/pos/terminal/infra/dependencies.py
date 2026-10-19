"""The POS headers: `X-Branch-Id` (checked against the user's branches by
`AuthMiddleware`) and `X-Terminal-Id`. Without them, and only with
`POS_TERMINAL_FALLBACK` (local, until the web sends them in S2.9), the request
runs in the main branch's first active terminal."""

import re

from fastapi import Depends, Header, Request

from config import config
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
    user: AuthenticatedUser = Depends(get_current_user),
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
    branch_id = getattr(request.state, "branch_id", None)
    if terminal is None:
        if not config.POS_TERMINAL_FALLBACK:
            raise TerminalRequiredError()
        return TerminalRequest(branch_id=branch_id, allowed_branches=user.branch_ids)
    value = terminal.strip()
    if not _TERMINAL_ID.fullmatch(value) or int(value) > _MAX_ID:
        raise InvalidTerminalHeaderError()
    if branch is None or branch_id is None:
        raise BranchRequiredError()
    return TerminalRequest(
        branch_id=branch_id, terminal_id=int(value), allowed_branches=user.branch_ids
    )


def pos_branch(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    branch: str | None = Header(
        None, alias="X-Branch-Id", description=_BRANCH_DESCRIPTION
    ),
) -> TerminalRequest:
    """The branch of a POS operation on an existing sale, shift or refund
    (`BRANCH_REQUIRED` without it)"""
    branch_id = getattr(request.state, "branch_id", None)
    if (branch is None or branch_id is None) and not config.POS_TERMINAL_FALLBACK:
        raise BranchRequiredError()
    return TerminalRequest(branch_id=branch_id, allowed_branches=user.branch_ids)
