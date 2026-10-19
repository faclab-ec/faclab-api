from unittest.mock import MagicMock

import pytest

from src.pos.refund.domain.entities import Refund
from src.pos.shift.domain.entities import Shift
from src.pos.terminal.app.guard import PosBranchGuard
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.app.scope import branch_scope, in_scope
from src.sales.domain.entities import Sale
from src.shared.domain.exceptions import NotFoundError
from tests.unit.pos.terminals import terminal_resolver

IN_BRANCH_1 = TerminalRequest(branch_id=1)


def _guard(sale=None, shift=None, refund=None) -> PosBranchGuard:
    sales, shifts, refunds = MagicMock(), MagicMock(), MagicMock()
    sales.get_by_id.return_value = sale
    shifts.get_by_id.return_value = shift
    refunds.get_by_id.return_value = refund
    return PosBranchGuard(terminal_resolver(), sales, shifts, refunds)


def test_a_sale_shift_or_refund_of_the_branch_passes():
    guard = _guard(
        sale=Sale(id=1, branch_id=1),
        shift=Shift(id=1, cashier_name="Ana", branch_id=1),
        refund=Refund(id=1, original_sale_id=1, branch_id=1),
    )

    guard.sale(1, IN_BRANCH_1)
    guard.shift(1, IN_BRANCH_1)
    guard.refund(1, IN_BRANCH_1)


def test_one_of_another_branch_is_not_found():
    guard = _guard(
        sale=Sale(id=1, branch_id=2),
        shift=Shift(id=1, cashier_name="Ana", branch_id=2),
        refund=Refund(id=1, original_sale_id=1, branch_id=2),
    )

    with pytest.raises(NotFoundError, match="Sale with id 1 not found"):
        guard.sale(1, IN_BRANCH_1)
    with pytest.raises(NotFoundError, match="Shift with id 1 not found"):
        guard.shift(1, IN_BRANCH_1)
    with pytest.raises(NotFoundError, match="Refund with id 1 not found"):
        guard.refund(1, IN_BRANCH_1)


def test_one_that_doesnt_exist_is_not_found():
    with pytest.raises(NotFoundError):
        _guard().sale(9, IN_BRANCH_1)


def test_rows_from_before_branches_pass():
    _guard(sale=Sale(id=1)).sale(1, IN_BRANCH_1)


def test_the_branch_scope_of_a_history():
    assert branch_scope(None, None) is None
    assert branch_scope(None, frozenset({1, 2})) == {1, 2}
    assert branch_scope(2, None) == {2}
    assert branch_scope(2, frozenset({1, 2})) == {2}


def test_a_history_of_a_branch_the_user_cant_enter():
    from src.auth.domain.exceptions import BranchAccessDeniedError

    with pytest.raises(BranchAccessDeniedError):
        branch_scope(3, frozenset({1, 2}))


def test_rows_without_branch_are_only_in_an_unlimited_scope():
    assert in_scope(None, None)
    assert in_scope(1, frozenset({1}))
    assert not in_scope(2, frozenset({1}))
    assert not in_scope(None, frozenset({1}))
