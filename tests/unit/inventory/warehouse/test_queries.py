"""Unit tests for Warehouse query handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.inventory.warehouse.app.queries.get_warehouse import (
    GetAllWarehousesQuery,
    GetAllWarehousesQueryHandler,
    GetWarehouseByIdQuery,
    GetWarehouseByIdQueryHandler,
)
from src.inventory.warehouse.domain.entities import Warehouse
from src.shared.domain.exceptions import NotFoundError

# --- Helpers ---


def _make_warehouse(**overrides) -> Warehouse:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "Main Warehouse",
        "code": "WH-01",
        "city": "Guayaquil",
        "country": "Ecuador",
        "is_active": True,
        "is_default": False,
    }
    defaults.update(overrides)
    return Warehouse(**defaults)


# --- GetAll ---


def test_get_all_warehouses_returns_all():
    warehouses = [
        _make_warehouse(id=1, code="WH-01"),
        _make_warehouse(id=2, code="WH-02", name="Secondary Warehouse"),
    ]
    repo = Mock()
    repo.get_all.return_value = warehouses
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery())

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["code"] == "WH-01"
    assert result[1]["id"] == 2
    assert result[1]["code"] == "WH-02"
    repo.get_all.assert_called_once()


def test_get_all_warehouses_empty_list():
    repo = Mock()
    repo.get_all.return_value = []
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery())

    assert result == []


def test_get_all_warehouses_filters_by_is_active_true():
    active_warehouses = [_make_warehouse(is_active=True)]
    repo = Mock()
    repo.filter_by.return_value = active_warehouses
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery(is_active=True))

    assert len(result) == 1
    assert result[0]["is_active"] is True
    repo.filter_by.assert_called_once_with(is_active=True)


def test_get_all_warehouses_filters_by_is_active_false():
    inactive = [_make_warehouse(is_active=False, name="Closed WH", code="CWH-01")]
    repo = Mock()
    repo.filter_by.return_value = inactive
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery(is_active=False))

    assert len(result) == 1
    assert result[0]["is_active"] is False
    repo.filter_by.assert_called_once_with(is_active=False)


def test_get_all_warehouses_no_filter_uses_get_all():
    repo = Mock()
    repo.get_all.return_value = []
    handler = GetAllWarehousesQueryHandler(repo)

    handler.handle(GetAllWarehousesQuery())

    repo.get_all.assert_called_once()
    repo.filter_by.assert_not_called()


def test_get_all_warehouses_returns_dict_fields():
    warehouse = _make_warehouse(
        manager="Jane Smith", phone="0987654321", email="jane@test.com"
    )
    repo = Mock()
    repo.get_all.return_value = [warehouse]
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery())

    assert result[0]["manager"] == "Jane Smith"
    assert result[0]["phone"] == "0987654321"
    assert result[0]["email"] == "jane@test.com"


# --- GetById ---


def test_get_warehouse_by_id_found():
    warehouse = _make_warehouse()
    repo = Mock()
    repo.get_by_id.return_value = warehouse
    handler = GetWarehouseByIdQueryHandler(repo)

    result = handler.handle(GetWarehouseByIdQuery(warehouse_id=1))

    assert result["id"] == 1
    assert result["name"] == "Main Warehouse"
    assert result["code"] == "WH-01"
    repo.get_by_id.assert_called_once_with(1)


def test_get_warehouse_by_id_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = GetWarehouseByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetWarehouseByIdQuery(warehouse_id=999))


def test_get_warehouse_by_id_returns_all_fields():
    warehouse = _make_warehouse(
        address="Av. Principal 123",
        is_default=True,
        country="Ecuador",
    )
    repo = Mock()
    repo.get_by_id.return_value = warehouse
    handler = GetWarehouseByIdQueryHandler(repo)

    result = handler.handle(GetWarehouseByIdQuery(warehouse_id=1))

    assert result["address"] == "Av. Principal 123"
    assert result["is_default"] is True
    assert result["country"] == "Ecuador"
