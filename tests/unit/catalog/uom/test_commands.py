"""Unit tests for UnitOfMeasure command handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.catalog.uom.app.commands.create import (
    CreateUnitOfMeasureCommand,
    CreateUnitOfMeasureCommandHandler,
)
from src.catalog.uom.app.commands.delete import (
    DeleteUnitOfMeasureCommand,
    DeleteUnitOfMeasureCommandHandler,
)
from src.catalog.uom.app.commands.update import (
    UpdateUnitOfMeasureCommand,
    UpdateUnitOfMeasureCommandHandler,
)
from src.catalog.uom.domain.entities import UnitOfMeasure
from src.shared.domain.exceptions import NotFoundError

# --- Helpers ---


def _make_uom(**overrides) -> UnitOfMeasure:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "Kilogram",
        "symbol": "kg",
        "description": "Unit of mass",
        "is_active": True,
    }
    defaults.update(overrides)
    return UnitOfMeasure(**defaults)


def _mock_repo(uom=None):
    repo = Mock()
    if uom is not None:
        repo.create.return_value = uom
        repo.update.return_value = uom
        repo.get_by_id.return_value = uom
    return repo


# --- Create ---


def test_create_uom_returns_dict_with_correct_fields():
    uom = _make_uom()
    repo = _mock_repo(uom=uom)
    handler = CreateUnitOfMeasureCommandHandler(repo)

    command = CreateUnitOfMeasureCommand(
        name="Kilogram",
        symbol="kg",
        description="Unit of mass",
    )
    result = handler.handle(command)

    assert result["id"] == 1
    assert result["name"] == "Kilogram"
    assert result["symbol"] == "kg"
    assert result["description"] == "Unit of mass"
    assert result["is_active"] is True


def test_create_uom_calls_repo_create():
    repo = _mock_repo(uom=_make_uom())
    handler = CreateUnitOfMeasureCommandHandler(repo)

    handler.handle(CreateUnitOfMeasureCommand(name="Unit", symbol="un"))

    repo.create.assert_called_once()
    created = repo.create.call_args[0][0]
    assert isinstance(created, UnitOfMeasure)
    assert created.symbol == "un"


def test_create_uom_inactive_by_default_is_overridable():
    uom = _make_uom(is_active=False)
    repo = _mock_repo(uom=uom)
    handler = CreateUnitOfMeasureCommandHandler(repo)

    result = handler.handle(
        CreateUnitOfMeasureCommand(name="Archived", symbol="ar", is_active=False)
    )

    assert result["is_active"] is False


def test_create_uom_without_description():
    uom = _make_uom(description=None)
    repo = _mock_repo(uom=uom)
    handler = CreateUnitOfMeasureCommandHandler(repo)

    result = handler.handle(CreateUnitOfMeasureCommand(name="Box", symbol="bx"))

    assert result["description"] is None


# --- Update ---


def test_update_uom_returns_updated_dict():
    existing = _make_uom(name="Old Name", symbol="old")
    updated = _make_uom(name="New Name", symbol="new")
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateUnitOfMeasureCommandHandler(repo)

    result = handler.handle(
        UpdateUnitOfMeasureCommand(uom_id=1, name="New Name", symbol="new")
    )

    assert result["name"] == "New Name"
    assert result["symbol"] == "new"
    repo.update.assert_called_once()


def test_update_uom_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateUnitOfMeasureCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateUnitOfMeasureCommand(uom_id=999, name="X", symbol="x"))


def test_update_uom_deactivate():
    existing = _make_uom(is_active=True)
    deactivated = _make_uom(is_active=False)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = deactivated
    handler = UpdateUnitOfMeasureCommandHandler(repo)

    result = handler.handle(
        UpdateUnitOfMeasureCommand(
            uom_id=1, name="Kilogram", symbol="kg", is_active=False
        )
    )

    assert result["is_active"] is False
    updated = repo.update.call_args[0][0]
    assert updated.is_active is False


# --- Delete ---


def test_delete_uom_calls_repo_delete():
    repo = _mock_repo(uom=_make_uom())
    handler = DeleteUnitOfMeasureCommandHandler(repo)

    result = handler.handle(DeleteUnitOfMeasureCommand(uom_id=1))

    assert result is None
    repo.delete.assert_called_once_with(1)


def test_delete_uom_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteUnitOfMeasureCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteUnitOfMeasureCommand(uom_id=999))


def test_delete_uom_does_not_delete_when_not_found():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteUnitOfMeasureCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteUnitOfMeasureCommand(uom_id=999))

    repo.delete.assert_not_called()
