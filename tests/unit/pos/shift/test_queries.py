from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pos.shift.app.queries.get_shifts import (
    GetActiveShiftQuery,
    GetActiveShiftQueryHandler,
    GetAllShiftsQuery,
    GetAllShiftsQueryHandler,
    GetShiftByIdQuery,
    GetShiftByIdQueryHandler,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.shared.domain.exceptions import NotFoundError


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
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    else:
        repo.first.return_value = None
        repo.get_by_id.return_value = None
    return repo


# --- GetActiveShift ---


def test_get_active_shift():
    """Test obtener el turno activo"""
    shift = _make_shift()
    repo = _mock_repo(entity=shift)
    handler = GetActiveShiftQueryHandler(repo)

    result = handler.handle(GetActiveShiftQuery())

    repo.first.assert_called_once_with(status="OPEN")
    assert result is not None
    assert result["status"] == "OPEN"
    assert result["cashier_name"] == "Juan"


def test_get_active_shift_none():
    """Test obtener turno activo cuando no hay ninguno"""
    repo = _mock_repo()
    handler = GetActiveShiftQueryHandler(repo)

    result = handler.handle(GetActiveShiftQuery())

    assert result is None


# --- GetShiftById ---


def test_get_shift_by_id():
    """Test obtener un turno por ID"""
    shift = _make_shift(id=1)
    repo = _mock_repo(entity=shift)
    handler = GetShiftByIdQueryHandler(repo)

    result = handler.handle(GetShiftByIdQuery(shift_id=1))

    repo.get_by_id.assert_called_once_with(1)
    assert result["id"] == 1
    assert result["cashier_name"] == "Juan"


def test_get_shift_by_id_not_found():
    """Test obtener un turno que no existe"""
    repo = _mock_repo()
    handler = GetShiftByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetShiftByIdQuery(shift_id=999))


# --- GetAllShifts ---


def test_get_all_shifts():
    """Test obtener todos los turnos"""
    shifts = [
        _make_shift(id=1, cashier_name="Juan"),
        _make_shift(id=2, cashier_name="Maria"),
    ]
    repo = _mock_repo()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in shifts],
    }
    handler = GetAllShiftsQueryHandler(repo)

    result = handler.handle(GetAllShiftsQuery())

    repo.paginate.assert_called_once_with(limit=None, offset=None)
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_all_shifts_with_status_filter():
    """Test filtrar turnos por estado"""
    shifts = [_make_shift(id=1, status=ShiftStatus.CLOSED)]
    repo = _mock_repo()
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in shifts],
    }
    handler = GetAllShiftsQueryHandler(repo)

    result = handler.handle(GetAllShiftsQuery(status="CLOSED"))

    repo.paginate.assert_called_once_with(limit=None, offset=None, status="CLOSED")
    assert len(result["items"]) == 1


def test_get_all_shifts_with_pagination():
    """Test paginacion de turnos"""
    shifts = [_make_shift(id=i) for i in range(1, 6)]
    repo = _mock_repo()
    repo.paginate.return_value = {
        "total": 10,
        "limit": 5,
        "offset": 0,
        "items": [s.dict() for s in shifts],
    }
    handler = GetAllShiftsQueryHandler(repo)

    result = handler.handle(GetAllShiftsQuery(limit=5, offset=0))

    repo.paginate.assert_called_once_with(limit=5, offset=0)
    assert len(result["items"]) == 5
    assert result["total"] == 10


def test_get_all_shifts_empty():
    """Test obtener turnos cuando no hay ninguno"""
    repo = _mock_repo()
    repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetAllShiftsQueryHandler(repo)

    result = handler.handle(GetAllShiftsQuery())

    assert len(result["items"]) == 0
    assert result["total"] == 0
