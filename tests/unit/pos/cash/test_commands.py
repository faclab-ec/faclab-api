from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pos.cash.app.commands.register_cash_movement import (
    RegisterCashMovementCommand,
    RegisterCashMovementCommandHandler,
)
from src.pos.cash.domain.entities import CashMovement, CashMovementType
from src.pos.cash.domain.exceptions import (
    InvalidCashMovementAmountError,
    ShiftNotOpenForCashMovementError,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail


def _make_shift(**overrides) -> Shift:
    defaults: dict[str, Any] = {
        "id": 1,
        "cashier_name": "Juan",
        "opening_balance": Decimal("500.00"),
        "status": ShiftStatus.OPEN,
    }
    defaults.update(overrides)
    return Shift(**defaults)


def _mock_repo(entity=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    else:
        repo.first.return_value = None
        repo.get_by_id.return_value = None
    return repo


def test_register_cash_movement_in():
    shift = _make_shift()
    shift_repo = _mock_repo(entity=shift)
    movement = CashMovement(
        shift_id=1,
        type=CashMovementType.IN,
        amount=Decimal("100.00"),
        reason="Cambio",
        id=1,
    )
    cash_repo = MagicMock()
    cash_repo.create.return_value = movement

    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )
    result = handler.handle(
        RegisterCashMovementCommand(
            shift_id=1,
            type="IN",
            amount=Decimal("100.00"),
            reason="Cambio",
        )
    )

    assert result["type"] == CashMovementType.IN
    assert result["amount"] == Decimal("100.00")
    cash_repo.create.assert_called_once()


def test_register_cash_movement_out():
    shift = _make_shift()
    shift_repo = _mock_repo(entity=shift)
    movement = CashMovement(
        shift_id=1,
        type=CashMovementType.OUT,
        amount=Decimal("50.00"),
        id=2,
    )
    cash_repo = MagicMock()
    cash_repo.create.return_value = movement

    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )
    result = handler.handle(
        RegisterCashMovementCommand(
            shift_id=1,
            type="OUT",
            amount=Decimal("50.00"),
        )
    )

    assert result["type"] == CashMovementType.OUT


def test_register_cash_movement_invalid_amount():
    shift_repo = MagicMock()
    cash_repo = MagicMock()
    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )

    with pytest.raises(InvalidCashMovementAmountError):
        handler.handle(
            RegisterCashMovementCommand(
                shift_id=1,
                type="IN",
                amount=Decimal("0"),
            )
        )


def test_register_cash_movement_negative_amount():
    shift_repo = MagicMock()
    cash_repo = MagicMock()
    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )

    with pytest.raises(InvalidCashMovementAmountError):
        handler.handle(
            RegisterCashMovementCommand(
                shift_id=1,
                type="IN",
                amount=Decimal("-10"),
            )
        )


def test_register_cash_movement_shift_not_found():
    shift_repo = _mock_repo()
    cash_repo = MagicMock()
    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )

    with pytest.raises(NotFoundError):
        handler.handle(
            RegisterCashMovementCommand(
                shift_id=999,
                type="IN",
                amount=Decimal("100.00"),
            )
        )


def test_register_cash_movement_shift_closed():
    shift = _make_shift(status=ShiftStatus.CLOSED)
    shift_repo = _mock_repo(entity=shift)
    cash_repo = MagicMock()
    handler = RegisterCashMovementCommandHandler(
        cash_repo, shift_repo, FakeAuditTrail()
    )

    with pytest.raises(ShiftNotOpenForCashMovementError):
        handler.handle(
            RegisterCashMovementCommand(
                shift_id=1,
                type="OUT",
                amount=Decimal("50.00"),
            )
        )
