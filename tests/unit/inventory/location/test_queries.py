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


def test_get_all_locations_returns_all():
    locations = [
        _make_location(id=1, code="A-01"),
        _make_location(id=2, code="B-01", name="Pasillo B"),
    ]
    repo = Mock()
    repo.get_all.return_value = locations
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery())

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2
    repo.get_all.assert_called_once()


def test_get_all_locations_empty_list():
    repo = Mock()
    repo.get_all.return_value = []
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery())

    assert result == []


def test_get_all_locations_filters_by_warehouse_id():
    locations = [_make_location(warehouse_id=10)]
    repo = Mock()
    repo.filter_by.return_value = locations
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery(warehouse_id=10))

    assert len(result) == 1
    assert result[0]["warehouse_id"] == 10
    repo.filter_by.assert_called_once_with(warehouse_id=10)


def test_get_all_locations_filters_by_is_active():
    active = [_make_location(is_active=True)]
    repo = Mock()
    repo.filter_by.return_value = active
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery(is_active=True))

    assert len(result) == 1
    assert result[0]["is_active"] is True
    repo.filter_by.assert_called_once_with(is_active=True)


def test_get_all_locations_filters_by_warehouse_and_is_active():
    locations = [_make_location(warehouse_id=10, is_active=True)]
    repo = Mock()
    repo.filter_by.return_value = locations
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery(warehouse_id=10, is_active=True))

    assert len(result) == 1
    call_kwargs = repo.filter_by.call_args.kwargs
    assert call_kwargs["warehouse_id"] == 10
    assert call_kwargs["is_active"] is True


def test_get_all_locations_no_filter_uses_get_all():
    repo = Mock()
    repo.get_all.return_value = []
    handler = GetAllLocationsQueryHandler(repo)

    handler.handle(GetAllLocationsQuery())

    repo.get_all.assert_called_once()
    repo.filter_by.assert_not_called()


def test_get_all_locations_returns_dict_with_type_field():
    locations = [
        _make_location(type=LocationType.RECEIVING),
        _make_location(id=2, code="SHP-01", type=LocationType.SHIPPING),
    ]
    repo = Mock()
    repo.get_all.return_value = locations
    handler = GetAllLocationsQueryHandler(repo)

    result = handler.handle(GetAllLocationsQuery())

    assert result[0]["type"] == LocationType.RECEIVING
    assert result[1]["type"] == LocationType.SHIPPING


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
