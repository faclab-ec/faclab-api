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


def _paginated(items: list[Warehouse], limit=None, offset=None) -> dict:
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": [w.dict() for w in items],
    }


def test_get_all_warehouses_returns_page():
    warehouses = [
        _make_warehouse(id=1, code="WH-01"),
        _make_warehouse(id=2, code="WH-02", name="Secondary Warehouse"),
    ]
    repo = Mock()
    repo.paginate.return_value = _paginated(warehouses)
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery())

    assert result["total"] == 2
    assert [w["code"] for w in result["items"]] == ["WH-01", "WH-02"]
    repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_all_warehouses_passes_pagination():
    repo = Mock()
    repo.paginate.return_value = _paginated([], limit=5, offset=10)
    handler = GetAllWarehousesQueryHandler(repo)

    handler.handle(GetAllWarehousesQuery(limit=5, offset=10))

    repo.paginate.assert_called_once_with(limit=5, offset=10)


def test_get_all_warehouses_filters_by_is_active_false():
    inactive = [_make_warehouse(is_active=False, name="Closed WH", code="CWH-01")]
    repo = Mock()
    repo.paginate.return_value = _paginated(inactive)
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery(is_active=False))

    assert result["items"][0]["is_active"] is False
    repo.paginate.assert_called_once_with(limit=None, offset=None, is_active=False)


def test_get_all_warehouses_returns_dict_fields():
    warehouse = _make_warehouse(
        manager="Jane Smith", phone="0987654321", email="jane@test.com"
    )
    repo = Mock()
    repo.paginate.return_value = _paginated([warehouse])
    handler = GetAllWarehousesQueryHandler(repo)

    result = handler.handle(GetAllWarehousesQuery())

    assert result["items"][0]["manager"] == "Jane Smith"
    assert result["items"][0]["email"] == "jane@test.com"


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
