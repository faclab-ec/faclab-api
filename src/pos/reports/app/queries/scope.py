from typing import Any

from src.pos.terminal.app.scope import branch_scope


def placement_criteria(
    model: Any,
    branch_id: int | None,
    terminal_id: int | None,
    branch_ids: frozenset[int] | None,
) -> list[Any]:
    """Filters of a POS report over sales or refunds (`model`): the branch and
    terminal asked for, within the branches the user may enter"""
    criteria = []
    scope = branch_scope(branch_id, branch_ids)
    if scope is not None:
        criteria.append(model.branch_id.in_(scope))
    if terminal_id is not None:
        criteria.append(model.terminal_id == terminal_id)
    return criteria
