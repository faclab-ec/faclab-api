from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.lot.app.commands.lot import (
    CreateLotCommand,
    CreateLotCommandHandler,
    UpdateLotCommand,
    UpdateLotCommandHandler,
)
from src.inventory.lot.domain.entities import Lot
from src.shared.domain.exceptions import DomainError, NotFoundError


def _make_lot(**overrides) -> Lot:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "lot_number": "LOT-001",
        "initial_quantity": 100,
        "current_quantity": 100,
    }
    defaults.update(overrides)
    return Lot(**defaults)


# ---------------------------------------------------------------------------
# CreateLotCommandHandler
# ---------------------------------------------------------------------------


def test_create_lot_success():
    lot = _make_lot()
    repo = MagicMock()
    repo.first.return_value = None
    repo.create.return_value = lot
    handler = CreateLotCommandHandler(repo)

    result = handler.handle(
        CreateLotCommand(product_id=5, lot_number="LOT-001", initial_quantity=100)
    )

    repo.create.assert_called_once()
    assert result["product_id"] == 5
    assert result["lot_number"] == "LOT-001"


def test_create_lot_duplicate_raises():
    existing_lot = _make_lot()
    repo = MagicMock()
    repo.first.return_value = existing_lot
    handler = CreateLotCommandHandler(repo)

    with pytest.raises(DomainError, match="already exists"):
        handler.handle(
            CreateLotCommand(product_id=5, lot_number="LOT-001", initial_quantity=100)
        )

    repo.create.assert_not_called()


def test_create_lot_sets_current_quantity_from_initial():
    lot = _make_lot(initial_quantity=50, current_quantity=50)
    repo = MagicMock()
    repo.first.return_value = None
    repo.create.return_value = lot
    handler = CreateLotCommandHandler(repo)

    handler.handle(
        CreateLotCommand(product_id=5, lot_number="LOT-001", initial_quantity=50)
    )

    created_lot = repo.create.call_args[0][0]
    assert created_lot.initial_quantity == 50
    assert created_lot.current_quantity == 50


# ---------------------------------------------------------------------------
# UpdateLotCommandHandler
# ---------------------------------------------------------------------------


def test_update_lot_quantity():
    lot = _make_lot(current_quantity=100)
    updated_lot = _make_lot(current_quantity=75)
    repo = MagicMock()
    repo.get_by_id.return_value = lot
    repo.update.return_value = updated_lot
    handler = UpdateLotCommandHandler(repo)

    result = handler.handle(UpdateLotCommand(id=1, current_quantity=75))

    repo.update.assert_called_once()
    assert result["current_quantity"] == 75


def test_update_lot_notes():
    lot = _make_lot(notes=None)
    updated_lot = _make_lot(notes="Updated notes")
    repo = MagicMock()
    repo.get_by_id.return_value = lot
    repo.update.return_value = updated_lot
    handler = UpdateLotCommandHandler(repo)

    result = handler.handle(UpdateLotCommand(id=1, notes="Updated notes"))

    repo.update.assert_called_once()
    assert result["notes"] == "Updated notes"


def test_update_lot_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateLotCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateLotCommand(id=99, current_quantity=50))


def test_update_lot_negative_quantity_raises():
    lot = _make_lot()
    repo = MagicMock()
    repo.get_by_id.return_value = lot
    handler = UpdateLotCommandHandler(repo)

    with pytest.raises(DomainError, match="cannot be negative"):
        handler.handle(UpdateLotCommand(id=1, current_quantity=-5))

    repo.update.assert_not_called()
