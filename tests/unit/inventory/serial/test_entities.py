from typing import Any

import pytest

from src.inventory.serial.domain.entities import SerialNumber, SerialStatus
from src.inventory.serial.domain.exceptions import InvalidSerialStatusError


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
# mark_sold
# ---------------------------------------------------------------------------


def test_mark_sold_from_available():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    serial.mark_sold()
    assert serial.status == SerialStatus.SOLD


def test_mark_sold_from_reserved_raises():
    serial = _make_serial(status=SerialStatus.RESERVED)
    with pytest.raises(InvalidSerialStatusError, match="as sold"):
        serial.mark_sold()


def test_mark_sold_from_sold_raises():
    serial = _make_serial(status=SerialStatus.SOLD)
    with pytest.raises(InvalidSerialStatusError):
        serial.mark_sold()


def test_mark_sold_from_returned_raises():
    serial = _make_serial(status=SerialStatus.RETURNED)
    with pytest.raises(InvalidSerialStatusError):
        serial.mark_sold()


# ---------------------------------------------------------------------------
# mark_reserved
# ---------------------------------------------------------------------------


def test_mark_reserved_from_available():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    serial.mark_reserved()
    assert serial.status == SerialStatus.RESERVED


def test_mark_reserved_from_sold_raises():
    serial = _make_serial(status=SerialStatus.SOLD)
    with pytest.raises(InvalidSerialStatusError, match="as reserved"):
        serial.mark_reserved()


def test_mark_reserved_from_reserved_raises():
    serial = _make_serial(status=SerialStatus.RESERVED)
    with pytest.raises(InvalidSerialStatusError):
        serial.mark_reserved()


# ---------------------------------------------------------------------------
# mark_returned
# ---------------------------------------------------------------------------


def test_mark_returned_from_sold():
    serial = _make_serial(status=SerialStatus.SOLD)
    serial.mark_returned()
    assert serial.status == SerialStatus.RETURNED


def test_mark_returned_from_available_raises():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    with pytest.raises(InvalidSerialStatusError, match="as returned"):
        serial.mark_returned()


def test_mark_returned_from_reserved_raises():
    serial = _make_serial(status=SerialStatus.RESERVED)
    with pytest.raises(InvalidSerialStatusError):
        serial.mark_returned()


# ---------------------------------------------------------------------------
# mark_scrapped
# ---------------------------------------------------------------------------


def test_mark_scrapped_from_available():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    serial.mark_scrapped()
    assert serial.status == SerialStatus.SCRAPPED


def test_mark_scrapped_from_sold():
    serial = _make_serial(status=SerialStatus.SOLD)
    serial.mark_scrapped()
    assert serial.status == SerialStatus.SCRAPPED


def test_mark_scrapped_from_returned():
    serial = _make_serial(status=SerialStatus.RETURNED)
    serial.mark_scrapped()
    assert serial.status == SerialStatus.SCRAPPED


def test_mark_scrapped_from_reserved():
    serial = _make_serial(status=SerialStatus.RESERVED)
    serial.mark_scrapped()
    assert serial.status == SerialStatus.SCRAPPED


def test_change_status_dispatches_to_the_transition():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    serial.change_status(SerialStatus.RESERVED)
    assert serial.status == SerialStatus.RESERVED


def test_change_status_to_available_is_not_allowed():
    serial = _make_serial(status=SerialStatus.SOLD)
    with pytest.raises(InvalidSerialStatusError):
        serial.change_status(SerialStatus.AVAILABLE)
    assert serial.status == SerialStatus.SOLD
