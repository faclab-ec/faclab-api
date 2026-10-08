from decimal import Decimal

import pytest

from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import ShiftAlreadyClosedError


def test_shift_created_with_open_status():
    """Test que un turno se crea con estado OPEN"""
    shift = Shift(cashier_name="Juan")
    assert shift.status == ShiftStatus.OPEN
    assert shift.opened_at is not None


def test_shift_created_with_opening_balance():
    """Test que un turno se crea con balance de apertura"""
    shift = Shift(cashier_name="Juan", opening_balance=Decimal("500.00"))
    assert shift.opening_balance == Decimal("500.00")


def test_shift_close_changes_status():
    """Test que cerrar un turno cambia su estado"""
    shift = Shift(cashier_name="Juan", opening_balance=Decimal("500.00"))
    shift.close(
        closing_balance=Decimal("600.00"),
        expected_balance=Decimal("500.00"),
    )
    assert shift.status == ShiftStatus.CLOSED
    assert shift.closed_at is not None


def test_shift_close_calculates_discrepancy():
    """Test que cerrar un turno calcula la discrepancia"""
    shift = Shift(cashier_name="Juan", opening_balance=Decimal("500.00"))
    discrepancy = shift.close(
        closing_balance=Decimal("600.00"),
        expected_balance=Decimal("550.00"),
    )
    assert shift.closing_balance == Decimal("600.00")
    assert shift.expected_balance == Decimal("550.00")
    assert shift.discrepancy == Decimal("50.00")
    assert discrepancy == Decimal("50.00")


def test_shift_close_negative_discrepancy():
    """Test que la discrepancia puede ser negativa"""
    shift = Shift(cashier_name="Juan", opening_balance=Decimal("500.00"))
    shift.close(
        closing_balance=Decimal("400.00"),
        expected_balance=Decimal("500.00"),
    )
    assert shift.discrepancy == Decimal("-100.00")


def test_shift_close_zero_discrepancy():
    """Test que la discrepancia puede ser cero"""
    shift = Shift(cashier_name="Juan", opening_balance=Decimal("500.00"))
    shift.close(
        closing_balance=Decimal("500.00"),
        expected_balance=Decimal("500.00"),
    )
    assert shift.discrepancy == Decimal("0")


def test_shift_close_already_closed_fails():
    """Test que no se puede cerrar un turno ya cerrado"""
    shift = Shift(
        cashier_name="Juan",
        opening_balance=Decimal("500.00"),
        id=1,
    )
    shift.close(
        closing_balance=Decimal("500.00"),
        expected_balance=Decimal("500.00"),
    )
    with pytest.raises(ShiftAlreadyClosedError):
        shift.close(
            closing_balance=Decimal("500.00"),
            expected_balance=Decimal("500.00"),
        )


def test_shift_default_nullable_fields():
    """Test que los campos opcionales son None por defecto"""
    shift = Shift(cashier_name="Juan")
    assert shift.closed_at is None
    assert shift.closing_balance is None
    assert shift.expected_balance is None
    assert shift.discrepancy is None
    assert shift.notes is None
    assert shift.id is None
