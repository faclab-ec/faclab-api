"""Unit tests for Location command handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.inventory.location.app.commands.create import (
    CreateLocationCommand,
    CreateLocationCommandHandler,
)
from src.inventory.location.app.commands.delete import (
    DeleteLocationCommand,
    DeleteLocationCommandHandler,
)
from src.inventory.location.app.commands.update import (
    UpdateLocationCommand,
    UpdateLocationCommandHandler,
)
from src.inventory.location.domain.entities import Location, LocationType
from src.shared.domain.exceptions import NotFoundError

# --- Helpers ---


def _make_location(**overrides) -> Location:
    defaults: dict[str, Any] = {
        "id": 1,
        "warehouse_id": 10,
        "name": "Pasillo A - Estante 1",
        "code": "A-01-001",
        "type": LocationType.STORAGE,
        "is_active": True,
        "capacity": 100,
    }
    defaults.update(overrides)
    return Location(**defaults)


def _mock_repo(location=None):
    repo = Mock()
    if location is not None:
        repo.create.return_value = location
        repo.update.return_value = location
        repo.get_by_id.return_value = location
    return repo


# --- Create ---


def test_create_location_returns_dict_with_correct_fields():
    location = _make_location()
    repo = _mock_repo(location=location)
    handler = CreateLocationCommandHandler(repo)

    result = handler.handle(
        CreateLocationCommand(
            warehouse_id=10,
            name="Pasillo A - Estante 1",
            code="A-01-001",
            type=LocationType.STORAGE,
        )
    )

    assert result["id"] == 1
    assert result["warehouse_id"] == 10
    assert result["name"] == "Pasillo A - Estante 1"
    assert result["code"] == "A-01-001"
    assert result["type"] == LocationType.STORAGE
    assert result["is_active"] is True


def test_create_location_calls_repo_create():
    repo = _mock_repo(location=_make_location())
    handler = CreateLocationCommandHandler(repo)

    handler.handle(
        CreateLocationCommand(warehouse_id=10, name="Receiving Area", code="REC-01")
    )

    repo.create.assert_called_once()
    created = repo.create.call_args[0][0]
    assert isinstance(created, Location)
    assert created.code == "REC-01"
    assert created.warehouse_id == 10


def test_create_location_default_type_is_storage():
    location = _make_location(type=LocationType.STORAGE)
    repo = _mock_repo(location=location)
    handler = CreateLocationCommandHandler(repo)

    handler.handle(
        CreateLocationCommand(warehouse_id=10, name="Default Zone", code="DZ-01")
    )

    created = repo.create.call_args[0][0]
    assert created.type == LocationType.STORAGE


def test_create_location_receiving_type():
    location = _make_location(type=LocationType.RECEIVING, code="REC-01")
    repo = _mock_repo(location=location)
    handler = CreateLocationCommandHandler(repo)

    result = handler.handle(
        CreateLocationCommand(
            warehouse_id=10,
            name="Receiving Dock",
            code="REC-01",
            type=LocationType.RECEIVING,
        )
    )

    assert result["type"] == LocationType.RECEIVING


def test_create_location_each_type_is_valid():
    for loc_type in LocationType:
        location = _make_location(type=loc_type)
        repo = _mock_repo(location=location)
        handler = CreateLocationCommandHandler(repo)

        result = handler.handle(
            CreateLocationCommand(
                warehouse_id=10,
                name=f"{loc_type} zone",
                code=f"{loc_type}-01",
                type=loc_type,
            )
        )

        assert result["type"] == loc_type


def test_create_location_without_capacity():
    location = _make_location(capacity=None)
    repo = _mock_repo(location=location)
    handler = CreateLocationCommandHandler(repo)

    result = handler.handle(
        CreateLocationCommand(warehouse_id=10, name="Open Zone", code="OZ-01")
    )

    assert result["capacity"] is None


def test_create_location_inactive():
    location = _make_location(is_active=False)
    repo = _mock_repo(location=location)
    handler = CreateLocationCommandHandler(repo)

    result = handler.handle(
        CreateLocationCommand(
            warehouse_id=10, name="Closed Zone", code="CLZ-01", is_active=False
        )
    )

    assert result["is_active"] is False


# --- Update ---


def test_update_location_returns_updated_dict():
    existing = _make_location(name="Old Name", code="OLD-01")
    updated = _make_location(name="New Name", code="NEW-01")
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateLocationCommandHandler(repo)

    result = handler.handle(
        UpdateLocationCommand(
            location_id=1,
            warehouse_id=10,
            name="New Name",
            code="NEW-01",
        )
    )

    assert result["name"] == "New Name"
    assert result["code"] == "NEW-01"
    repo.update.assert_called_once()


def test_update_location_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateLocationCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(
            UpdateLocationCommand(
                location_id=999, warehouse_id=10, name="X", code="X-01"
            )
        )


def test_update_location_not_found_does_not_call_update():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateLocationCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(
            UpdateLocationCommand(
                location_id=999, warehouse_id=10, name="X", code="X-01"
            )
        )

    repo.update.assert_not_called()


def test_update_location_change_type():
    existing = _make_location(type=LocationType.STORAGE)
    updated = _make_location(type=LocationType.DAMAGED)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateLocationCommandHandler(repo)

    result = handler.handle(
        UpdateLocationCommand(
            location_id=1,
            warehouse_id=10,
            name="Damage Zone",
            code="DMG-01",
            type=LocationType.DAMAGED,
        )
    )

    assert result["type"] == LocationType.DAMAGED
    updated_entity = repo.update.call_args[0][0]
    assert updated_entity.type == LocationType.DAMAGED


def test_update_location_deactivate():
    existing = _make_location(is_active=True)
    deactivated = _make_location(is_active=False)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = deactivated
    handler = UpdateLocationCommandHandler(repo)

    result = handler.handle(
        UpdateLocationCommand(
            location_id=1, warehouse_id=10, name="Zone A", code="ZA-01", is_active=False
        )
    )

    assert result["is_active"] is False


# --- Delete ---


def test_delete_location_calls_repo_delete():
    repo = _mock_repo(location=_make_location())
    handler = DeleteLocationCommandHandler(repo)

    result = handler.handle(DeleteLocationCommand(location_id=1))

    assert result is None
    repo.delete.assert_called_once_with(1)


def test_delete_location_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteLocationCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteLocationCommand(location_id=999))


def test_delete_location_not_found_does_not_delete():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteLocationCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteLocationCommand(location_id=999))

    repo.delete.assert_not_called()
