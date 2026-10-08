from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.serial.app.queries.serial import (
    GetSerialByIdQuery,
    GetSerialByIdQueryHandler,
    GetSerialByNumberQuery,
    GetSerialByNumberQueryHandler,
    GetSerialsQuery,
    GetSerialsQueryHandler,
)
from src.inventory.serial.domain.entities import SerialNumber, SerialStatus
from src.shared.domain.exceptions import NotFoundError


def _make_serial(**overrides) -> SerialNumber:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "serial_number": "SN-001",
        "status": SerialStatus.AVAILABLE,
    }
    defaults.update(overrides)
    return SerialNumber(**defaults)


# ---------------------------------------------------------------------------
# GetSerialsQueryHandler
# ---------------------------------------------------------------------------


def test_get_serials_by_product():
    s1 = _make_serial(id=1, serial_number="SN-001")
    s2 = _make_serial(id=2, serial_number="SN-002")
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s1.dict(), s2.dict()],
    }
    handler = GetSerialsQueryHandler(repo)

    result = handler.handle(GetSerialsQuery(product_id=5))

    repo.paginate.assert_called_once_with(limit=None, offset=None, product_id=5)
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_serials_with_status_filter():
    s1 = _make_serial(status=SerialStatus.AVAILABLE)
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [s1.dict()],
    }
    handler = GetSerialsQueryHandler(repo)

    result = handler.handle(GetSerialsQuery(product_id=5, status="available"))

    repo.paginate.assert_called_once_with(
        limit=None, offset=None, product_id=5, status="available"
    )
    assert len(result["items"]) == 1
    assert result["total"] == 1


def test_get_serials_without_filters():
    s1 = _make_serial(id=1, serial_number="SN-001")
    s2 = _make_serial(id=2, serial_number="SN-002")
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s1.dict(), s2.dict()],
    }
    handler = GetSerialsQueryHandler(repo)

    result = handler.handle(GetSerialsQuery())

    repo.paginate.assert_called_once_with(limit=None, offset=None)
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_serials_by_product_empty():
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetSerialsQueryHandler(repo)

    result = handler.handle(GetSerialsQuery(product_id=99))
    assert result["items"] == []
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# GetSerialByNumberQueryHandler
# ---------------------------------------------------------------------------


def test_get_serial_by_number():
    serial = _make_serial()
    repo = MagicMock()
    repo.first.return_value = serial
    handler = GetSerialByNumberQueryHandler(repo)

    result = handler.handle(GetSerialByNumberQuery(serial_number="SN-001"))

    repo.first.assert_called_once_with(serial_number="SN-001")
    assert result["serial_number"] == "SN-001"


def test_get_serial_by_number_not_found_raises():
    repo = MagicMock()
    repo.first.return_value = None
    handler = GetSerialByNumberQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetSerialByNumberQuery(serial_number="NONEXISTENT"))


# ---------------------------------------------------------------------------
# GetSerialByIdQueryHandler
# ---------------------------------------------------------------------------


def test_get_serial_by_id():
    serial = _make_serial()
    repo = MagicMock()
    repo.get_by_id.return_value = serial
    handler = GetSerialByIdQueryHandler(repo)

    result = handler.handle(GetSerialByIdQuery(id=1))

    repo.get_by_id.assert_called_once_with(1)
    assert result["id"] == 1


def test_get_serial_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetSerialByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetSerialByIdQuery(id=99))
