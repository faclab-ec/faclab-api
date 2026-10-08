from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.serial.app.commands.serial import (
    CreateSerialNumberCommand,
    CreateSerialNumberCommandHandler,
    UpdateSerialStatusCommand,
    UpdateSerialStatusCommandHandler,
)
from src.inventory.serial.domain.entities import SerialNumber, SerialStatus
from src.shared.domain.exceptions import DomainError, NotFoundError


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
# CreateSerialNumberCommandHandler
# ---------------------------------------------------------------------------


def test_create_serial_success():
    serial = _make_serial()
    repo = MagicMock()
    repo.first.return_value = None
    repo.create.return_value = serial
    handler = CreateSerialNumberCommandHandler(repo)

    result = handler.handle(
        CreateSerialNumberCommand(product_id=5, serial_number="SN-001")
    )

    repo.create.assert_called_once()
    assert result["serial_number"] == "SN-001"
    assert result["status"] == SerialStatus.AVAILABLE


def test_create_serial_duplicate_raises():
    existing = _make_serial()
    repo = MagicMock()
    repo.first.return_value = existing
    handler = CreateSerialNumberCommandHandler(repo)

    with pytest.raises(DomainError, match="already exists"):
        handler.handle(CreateSerialNumberCommand(product_id=5, serial_number="SN-001"))

    repo.create.assert_not_called()


def test_create_serial_with_lot_id():
    serial = _make_serial(lot_id=3)
    repo = MagicMock()
    repo.first.return_value = None
    repo.create.return_value = serial
    handler = CreateSerialNumberCommandHandler(repo)

    handler.handle(
        CreateSerialNumberCommand(product_id=5, serial_number="SN-001", lot_id=3)
    )

    created = repo.create.call_args[0][0]
    assert created.lot_id == 3


# ---------------------------------------------------------------------------
# UpdateSerialStatusCommandHandler
# ---------------------------------------------------------------------------


def test_update_status_to_sold():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    sold_serial = _make_serial(status=SerialStatus.SOLD)
    repo = MagicMock()
    repo.get_by_id.return_value = serial
    repo.update.return_value = sold_serial
    handler = UpdateSerialStatusCommandHandler(repo)

    result = handler.handle(UpdateSerialStatusCommand(id=1, status="sold"))

    repo.update.assert_called_once()
    assert result["status"] == SerialStatus.SOLD


def test_update_status_to_reserved():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    reserved_serial = _make_serial(status=SerialStatus.RESERVED)
    repo = MagicMock()
    repo.get_by_id.return_value = serial
    repo.update.return_value = reserved_serial
    handler = UpdateSerialStatusCommandHandler(repo)

    result = handler.handle(UpdateSerialStatusCommand(id=1, status="reserved"))
    assert result["status"] == SerialStatus.RESERVED


def test_update_status_invalid_transition_raises():
    serial = _make_serial(status=SerialStatus.SOLD)
    repo = MagicMock()
    repo.get_by_id.return_value = serial
    handler = UpdateSerialStatusCommandHandler(repo)

    with pytest.raises(DomainError):
        handler.handle(UpdateSerialStatusCommand(id=1, status="reserved"))


def test_update_status_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateSerialStatusCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateSerialStatusCommand(id=99, status="sold"))


def test_update_status_invalid_value_raises_domain_error():
    serial = _make_serial(status=SerialStatus.AVAILABLE)
    repo = MagicMock()
    repo.get_by_id.return_value = serial
    handler = UpdateSerialStatusCommandHandler(repo)

    with pytest.raises(DomainError, match="Invalid serial status"):
        handler.handle(UpdateSerialStatusCommand(id=1, status="invalid_status"))

    repo.update.assert_not_called()


def test_update_status_to_scrapped_from_any():
    for status in [
        SerialStatus.AVAILABLE,
        SerialStatus.SOLD,
        SerialStatus.RESERVED,
        SerialStatus.RETURNED,
    ]:
        serial = _make_serial(status=status)
        scrapped = _make_serial(status=SerialStatus.SCRAPPED)
        repo = MagicMock()
        repo.get_by_id.return_value = serial
        repo.update.return_value = scrapped
        handler = UpdateSerialStatusCommandHandler(repo)

        result = handler.handle(UpdateSerialStatusCommand(id=1, status="scrapped"))
        assert result["status"] == SerialStatus.SCRAPPED
