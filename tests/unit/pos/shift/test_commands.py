from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.pos.shift.app.commands.close_shift import (
    CloseShiftCommand,
    CloseShiftCommandHandler,
)
from src.pos.shift.app.commands.open_shift import (
    OpenShiftCommand,
    OpenShiftCommandHandler,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import (
    ShiftAlreadyClosedError,
    ShiftAlreadyOpenError,
)
from src.shared.domain.exceptions import NotFoundError

_ZERO_SUMMARY = {
    "cash_sales": Decimal("0"),
    "cash_refunds": Decimal("0"),
    "cash_in": Decimal("0"),
    "cash_out": Decimal("0"),
}


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


# --- OpenShift ---


def test_open_shift_command_handler():
    """Test abrir un turno exitosamente"""
    shift = _make_shift()
    repo = _mock_repo()
    repo.create.return_value = shift
    event_publisher = MagicMock()
    handler = OpenShiftCommandHandler(repo, event_publisher)

    command = OpenShiftCommand(
        cashier_name="Juan",
        opening_balance=Decimal("500.00"),
    )
    result = handler.handle(command)

    repo.first.assert_called_once_with(status="OPEN")
    repo.create.assert_called_once()
    assert result["cashier_name"] == "Juan"
    assert result["status"] == "OPEN"


def test_open_shift_publishes_event():
    """Test que abrir un turno publica evento"""
    from src.pos.shift.domain.events import ShiftOpened

    shift = _make_shift()
    repo = _mock_repo()
    repo.create.return_value = shift
    event_publisher = MagicMock()
    handler = OpenShiftCommandHandler(repo, event_publisher)

    handler.handle(
        OpenShiftCommand(cashier_name="Juan", opening_balance=Decimal("500.00"))
    )

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, ShiftOpened)
    assert published_event.shift_id == 1
    assert published_event.cashier_name == "Juan"


def test_open_shift_fails_if_already_open():
    """Test que falla si ya hay un turno abierto"""
    existing_shift = _make_shift()
    repo = _mock_repo(entity=existing_shift)
    handler = OpenShiftCommandHandler(repo, MagicMock())

    command = OpenShiftCommand(
        cashier_name="Maria",
        opening_balance=Decimal("300.00"),
    )

    with pytest.raises(ShiftAlreadyOpenError):
        handler.handle(command)


# --- CloseShift ---


@patch("src.pos.shift.app.commands.close_shift.compute_cash_summary")
def test_close_shift_command_handler(mock_summary):
    """Test cerrar un turno exitosamente"""
    mock_summary.return_value = _ZERO_SUMMARY
    shift = _make_shift()
    repo = _mock_repo(entity=shift)
    event_publisher = MagicMock()
    session = MagicMock()
    handler = CloseShiftCommandHandler(repo, event_publisher, session)

    command = CloseShiftCommand(
        shift_id=1,
        closing_balance=Decimal("600.00"),
    )
    result = handler.handle(command)

    repo.get_by_id.assert_called_once_with(1)
    repo.update.assert_called_once()
    assert result["status"] == "CLOSED"
    assert result["closing_balance"] == Decimal("600.00")


@patch("src.pos.shift.app.commands.close_shift.compute_cash_summary")
def test_close_shift_publishes_event(mock_summary):
    """Test que cerrar un turno publica evento"""
    mock_summary.return_value = _ZERO_SUMMARY
    from src.pos.shift.domain.events import ShiftClosed

    shift = _make_shift()
    repo = _mock_repo(entity=shift)
    event_publisher = MagicMock()
    session = MagicMock()
    handler = CloseShiftCommandHandler(repo, event_publisher, session)

    handler.handle(CloseShiftCommand(shift_id=1, closing_balance=Decimal("600.00")))

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, ShiftClosed)
    assert published_event.shift_id == 1


def test_close_shift_not_found():
    """Test que falla si el turno no existe"""
    repo = _mock_repo()
    session = MagicMock()
    handler = CloseShiftCommandHandler(repo, MagicMock(), session)

    command = CloseShiftCommand(shift_id=999, closing_balance=Decimal("500.00"))

    with pytest.raises(NotFoundError):
        handler.handle(command)


@patch("src.pos.shift.app.commands.close_shift.compute_cash_summary")
def test_close_shift_already_closed(mock_summary):
    """Test que falla si el turno ya esta cerrado"""
    mock_summary.return_value = _ZERO_SUMMARY
    shift = _make_shift(status=ShiftStatus.CLOSED)
    repo = _mock_repo(entity=shift)
    session = MagicMock()
    handler = CloseShiftCommandHandler(repo, MagicMock(), session)

    command = CloseShiftCommand(shift_id=1, closing_balance=Decimal("500.00"))

    with pytest.raises(ShiftAlreadyClosedError):
        handler.handle(command)


@patch("src.pos.shift.app.commands.close_shift.compute_cash_summary")
def test_close_shift_with_notes(mock_summary):
    """Test cerrar turno con notas"""
    mock_summary.return_value = _ZERO_SUMMARY
    shift = _make_shift()
    repo = _mock_repo(entity=shift)
    session = MagicMock()
    handler = CloseShiftCommandHandler(repo, MagicMock(), session)

    command = CloseShiftCommand(
        shift_id=1,
        closing_balance=Decimal("500.00"),
        notes="Turno sin novedades",
    )
    result = handler.handle(command)

    assert result["notes"] == "Turno sin novedades"
