from src.auth.domain.exceptions import BranchAccessDeniedError


def branch_scope(
    branch_id: int | None, allowed: frozenset[int] | None
) -> frozenset[int] | None:
    """The branches a POS history or report covers: the one asked for, which
    the user must be able to enter, or else all the user's (None: all)"""
    if branch_id is None:
        return allowed
    if allowed is not None and branch_id not in allowed:
        raise BranchAccessDeniedError()
    return frozenset({branch_id})


def in_scope(branch_id: int | None, scope: frozenset[int] | None) -> bool:
    """A shift, sale or refund of a branch in the scope. Those from before
    S2.6 have no branch: only an unlimited scope sees them."""
    return scope is None or branch_id in scope
