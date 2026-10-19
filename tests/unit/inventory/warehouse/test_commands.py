"""Unit tests for Warehouse command handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.inventory.warehouse.app.commands.create import (
    CreateWarehouseCommand,
    CreateWarehouseCommandHandler,
)
from src.inventory.warehouse.app.commands.delete import (
    DeleteWarehouseCommand,
    DeleteWarehouseCommandHandler,
)
from src.inventory.warehouse.app.commands.update import (
    UpdateWarehouseCommand,
    UpdateWarehouseCommandHandler,
)
from src.inventory.warehouse.domain.entities import Warehouse
from src.shared.domain.exceptions import NotFoundError

# --- Helpers ---


def _make_warehouse(**overrides) -> Warehouse:
    defaults: dict[str, Any] = {
        "id": 1,
        "branch_id": 1,
        "name": "Main Warehouse",
        "code": "WH-01",
        "address": "Av. Principal 123",
        "city": "Guayaquil",
        "country": "Ecuador",
        "is_active": True,
        "is_default": False,
        "manager": "John Doe",
        "phone": "0999999999",
        "email": "warehouse@test.com",
    }
    defaults.update(overrides)
    return Warehouse(**defaults)


def _mock_repo(warehouse=None):
    repo = Mock()
    if warehouse is not None:
        repo.create.return_value = warehouse
        repo.update.return_value = warehouse
        repo.get_by_id.return_value = warehouse
    return repo


# --- Create ---


def test_create_warehouse_returns_dict_with_correct_fields():
    warehouse = _make_warehouse()
    repo = _mock_repo(warehouse=warehouse)
    handler = CreateWarehouseCommandHandler(repo)

    result = handler.handle(
        CreateWarehouseCommand(
            branch_id=1,
            name="Main Warehouse",
            code="WH-01",
            city="Guayaquil",
            country="Ecuador",
        )
    )

    assert result["id"] == 1
    assert result["name"] == "Main Warehouse"
    assert result["code"] == "WH-01"
    assert result["city"] == "Guayaquil"
    assert result["is_active"] is True
    assert result["is_default"] is False


def test_create_warehouse_calls_repo_create():
    repo = _mock_repo(warehouse=_make_warehouse())
    handler = CreateWarehouseCommandHandler(repo)

    handler.handle(CreateWarehouseCommand(branch_id=3, name="Depot", code="DP-01"))

    repo.create.assert_called_once()
    created = repo.create.call_args[0][0]
    assert isinstance(created, Warehouse)
    assert created.code == "DP-01"
    assert created.branch_id == 3


def test_create_warehouse_minimal_fields():
    warehouse = _make_warehouse(
        address=None, city=None, country=None, manager=None, phone=None, email=None
    )
    repo = _mock_repo(warehouse=warehouse)
    handler = CreateWarehouseCommandHandler(repo)

    result = handler.handle(
        CreateWarehouseCommand(branch_id=1, name="Simple", code="SP-01")
    )

    assert result["id"] == 1
    assert result["address"] is None
    assert result["manager"] is None


def test_create_warehouse_default_warehouse():
    warehouse = _make_warehouse(is_default=True)
    repo = _mock_repo(warehouse=warehouse)
    handler = CreateWarehouseCommandHandler(repo)

    result = handler.handle(
        CreateWarehouseCommand(
            branch_id=1, name="Default WH", code="DWH-01", is_default=True
        )
    )

    assert result["is_default"] is True
    created = repo.create.call_args[0][0]
    assert created.is_default is True


def test_create_warehouse_inactive():
    warehouse = _make_warehouse(is_active=False)
    repo = _mock_repo(warehouse=warehouse)
    handler = CreateWarehouseCommandHandler(repo)

    result = handler.handle(
        CreateWarehouseCommand(
            branch_id=1, name="Closed WH", code="CWH-01", is_active=False
        )
    )

    assert result["is_active"] is False


# --- Update ---


def test_update_warehouse_returns_updated_dict():
    existing = _make_warehouse(name="Old Name", code="OLD-01")
    updated = _make_warehouse(name="New Name", code="NEW-01")
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateWarehouseCommandHandler(repo)

    result = handler.handle(
        UpdateWarehouseCommand(warehouse_id=1, name="New Name", code="NEW-01")
    )

    assert result["name"] == "New Name"
    assert result["code"] == "NEW-01"
    repo.update.assert_called_once()


def test_update_warehouse_keeps_its_branch():
    repo = Mock()
    repo.get_by_id.return_value = _make_warehouse(branch_id=7)
    repo.update.side_effect = lambda warehouse: warehouse
    handler = UpdateWarehouseCommandHandler(repo)

    result = handler.handle(
        UpdateWarehouseCommand(warehouse_id=1, name="New Name", code="NEW-01")
    )

    assert result["branch_id"] == 7


def test_update_warehouse_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateWarehouseCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateWarehouseCommand(warehouse_id=999, name="X", code="X-01"))


def test_update_warehouse_not_found_does_not_call_update():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = UpdateWarehouseCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateWarehouseCommand(warehouse_id=999, name="X", code="X-01"))

    repo.update.assert_not_called()


def test_update_warehouse_deactivate():
    existing = _make_warehouse(is_active=True)
    deactivated = _make_warehouse(is_active=False)
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = deactivated
    handler = UpdateWarehouseCommandHandler(repo)

    result = handler.handle(
        UpdateWarehouseCommand(
            warehouse_id=1, name="Main WH", code="WH-01", is_active=False
        )
    )

    assert result["is_active"] is False
    updated = repo.update.call_args[0][0]
    assert updated.is_active is False


def test_update_warehouse_change_manager():
    existing = _make_warehouse(manager="Old Manager")
    updated = _make_warehouse(manager="New Manager")
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.update.return_value = updated
    handler = UpdateWarehouseCommandHandler(repo)

    result = handler.handle(
        UpdateWarehouseCommand(
            warehouse_id=1, name="Main WH", code="WH-01", manager="New Manager"
        )
    )

    assert result["manager"] == "New Manager"


# --- Delete ---


def test_delete_warehouse_calls_repo_delete():
    repo = _mock_repo(warehouse=_make_warehouse())
    handler = DeleteWarehouseCommandHandler(repo)

    result = handler.handle(DeleteWarehouseCommand(warehouse_id=1))

    assert result is None
    repo.delete.assert_called_once_with(1)


def test_delete_warehouse_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteWarehouseCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteWarehouseCommand(warehouse_id=999))


def test_delete_warehouse_not_found_does_not_delete():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = DeleteWarehouseCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(DeleteWarehouseCommand(warehouse_id=999))

    repo.delete.assert_not_called()
