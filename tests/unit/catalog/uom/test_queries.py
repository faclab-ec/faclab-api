"""Unit tests for UnitOfMeasure query handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.catalog.uom.app.queries.get_uom import (
    GetAllUnitsOfMeasureQuery,
    GetAllUnitsOfMeasureQueryHandler,
    GetUnitOfMeasureByIdQuery,
    GetUnitOfMeasureByIdQueryHandler,
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


# --- GetAll ---


def test_get_all_uom_returns_all():
    uoms = [_make_uom(id=1), _make_uom(id=2, name="Liter", symbol="L")]
    repo = Mock()
    repo.filter_by.return_value = uoms
    repo.count_by.return_value = 2
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    result = handler.handle(GetAllUnitsOfMeasureQuery())

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2
    assert result["total"] == 2
    repo.filter_by.assert_called_once()


def test_get_all_uom_empty_list():
    repo = Mock()
    repo.filter_by.return_value = []
    repo.count_by.return_value = 0
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    result = handler.handle(GetAllUnitsOfMeasureQuery())

    assert result["items"] == []
    assert result["total"] == 0


def test_get_all_uom_filters_by_is_active_true():
    active_uoms = [_make_uom(is_active=True)]
    repo = Mock()
    repo.filter_by.return_value = active_uoms
    repo.count_by.return_value = 1
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    result = handler.handle(GetAllUnitsOfMeasureQuery(is_active=True))

    assert len(result["items"]) == 1
    assert result["items"][0]["is_active"] is True
    assert result["total"] == 1
    repo.filter_by.assert_called_once_with(is_active=True, limit=None, offset=None)
    repo.count_by.assert_called_once_with(is_active=True)


def test_get_all_uom_filters_by_is_active_false():
    inactive_uoms = [_make_uom(is_active=False, name="Archived", symbol="ar")]
    repo = Mock()
    repo.filter_by.return_value = inactive_uoms
    repo.count_by.return_value = 1
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    result = handler.handle(GetAllUnitsOfMeasureQuery(is_active=False))

    assert len(result["items"]) == 1
    assert result["items"][0]["is_active"] is False
    assert result["total"] == 1
    repo.filter_by.assert_called_once_with(is_active=False, limit=None, offset=None)
    repo.count_by.assert_called_once_with(is_active=False)


def test_get_all_uom_without_filter_does_not_pass_is_active():
    repo = Mock()
    repo.filter_by.return_value = []
    repo.count_by.return_value = 0
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    handler.handle(GetAllUnitsOfMeasureQuery())

    # When is_active is None, should NOT pass it to filter_by
    call_kwargs = repo.filter_by.call_args
    assert "is_active" not in (call_kwargs.kwargs if call_kwargs.kwargs else {})


def test_get_all_uom_with_pagination():
    repo = Mock()
    repo.filter_by.return_value = [_make_uom()]
    repo.count_by.return_value = 1
    handler = GetAllUnitsOfMeasureQueryHandler(repo)

    handler.handle(GetAllUnitsOfMeasureQuery(limit=10, offset=20))

    repo.filter_by.assert_called_once_with(limit=10, offset=20)


# --- GetById ---


def test_get_uom_by_id_found():
    uom = _make_uom()
    repo = Mock()
    repo.get_by_id.return_value = uom
    handler = GetUnitOfMeasureByIdQueryHandler(repo)

    result = handler.handle(GetUnitOfMeasureByIdQuery(uom_id=1))

    assert result["id"] == 1
    assert result["name"] == "Kilogram"
    assert result["symbol"] == "kg"
    repo.get_by_id.assert_called_once_with(1)


def test_get_uom_by_id_not_found_raises():
    repo = Mock()
    repo.get_by_id.return_value = None
    handler = GetUnitOfMeasureByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetUnitOfMeasureByIdQuery(uom_id=999))


def test_get_uom_by_id_returns_all_fields():
    uom = _make_uom(description="Unit of mass", is_active=False)
    repo = Mock()
    repo.get_by_id.return_value = uom
    handler = GetUnitOfMeasureByIdQueryHandler(repo)

    result = handler.handle(GetUnitOfMeasureByIdQuery(uom_id=1))

    assert result["description"] == "Unit of mass"
    assert result["is_active"] is False
