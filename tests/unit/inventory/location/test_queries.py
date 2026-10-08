"""Unit tests for Location query handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.inventory.location.app.queries.get_location import (
    GetAllLocationsQuery,
    GetAllLocationsQueryHandler,
    GetLocationByIdQuery,
    GetLocationByIdQueryHandler,
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
        "capacity": None,
    }
    defaults.update(overrides)
    return Location(**defaults)


# --- GetAll ---


def _paginated(items: list[Location], limit=None, offset=None) -> dict:
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": [loc.dict() for loc in items],
    }


def test_get_all_locations_returns_page():
    locations = [
        _make_location(id=1, code="A-01"),
        _make_location(id=2, code="B-01", name="Pasillo B"),
    ]
    repo = Mock()
    repo.paginate.return_value = _paginated(locations)
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery())

    assert result["total"] == 2
    assert [loc["id"] for loc in result["items"]] == [1, 2]
    repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_all_locations_passes_pagination():
    repo = Mock()
    repo.paginate.return_value = _paginated([], limit=10, offset=20)
    handler = GetAllLocationsQueryHandler(repo)

    handler.handle(GetAllLocationsQuery(limit=10, offset=20))

    repo.paginate.assert_called_once_with(limit=10, offset=20)


def test_get_all_locations_filters_by_warehouse_id():
    repo = Mock()
    repo.paginate.return_value = _paginated([_make_location(warehouse_id=10)])
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery(warehouse_id=10))

    assert result["items"][0]["warehouse_id"] == 10
    repo.paginate.assert_called_once_with(limit=None, offset=None, warehouse_id=10)


def test_get_all_locations_filters_by_warehouse_and_is_active():
    repo = Mock()
    repo.paginate.return_value = _paginated([_make_location()])
    handler = GetAllLocationsQueryHandler(repo)

    handler.handle(GetAllLocationsQuery(warehouse_id=10, is_active=False))

    repo.paginate.assert_called_once_with(
        limit=None, offset=None, warehouse_id=10, is_active=False
    )


def test_get_all_locations_returns_dict_with_type_field():
    locations = [
        _make_location(type=LocationType.RECEIVING),
        _make_location(id=2, code="SHP-01", type=LocationType.SHIPPING),
    ]
    repo = Mock()
    repo.paginate.return_value = _paginated(locations)
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery())

    assert result["items"][0]["type"] == LocationType.RECEIVING
    assert result["items"][1]["type"] == LocationType.SHIPPING


# --- GetById ---


def test_get_location_by_id_found():
    location = _make_location()
    repo = Mock()
    repo.get_by_id.return_value = location
    handler = GetLocationByIdQueryHandler(repo)

    result = handler.handle(GetLocationByIdQuery(location_id=1))

    assert result["id"] == 1
    assert result["warehouse_id"] == 10
    assert result["code"] == "A-01-001"
    assert result["type"] == LocationType.STORAGE
    repo.get_by_id.assert_called_once_with(1)


def test_get_location_by_id_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = GetLocationByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetLocationByIdQuery(location_id=999))


def test_get_location_by_id_returns_all_fields():
    location = _make_location(
        type=LocationType.QUALITY,
        capacity=50,
        is_active=False,
    )
    repo = Mock()
    repo.get_by_id.return_value = location
    handler = GetLocationByIdQueryHandler(repo)

    result = handler.handle(GetLocationByIdQuery(location_id=1))

    assert result["type"] == LocationType.QUALITY
    assert result["capacity"] == 50
    assert result["is_active"] is False
