from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.lot.app.queries.lot import (
    GetAllLotsQuery,
    GetAllLotsQueryHandler,
    GetLotByIdQuery,
    GetLotByIdQueryHandler,
)
from src.inventory.lot.domain.entities import Lot
from src.shared.domain.exceptions import NotFoundError


def _make_lot(**overrides) -> Lot:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "lot_number": "LOT-001",
        "initial_quantity": 100,
        "current_quantity": 80,
    }
    defaults.update(overrides)
    return Lot(**defaults)


# ---------------------------------------------------------------------------
# GetAllLotsQueryHandler
# ---------------------------------------------------------------------------


def test_get_all_lots():
    lot1 = _make_lot(id=1, lot_number="LOT-001")
    lot2 = _make_lot(id=2, lot_number="LOT-002")
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [lot1.dict(), lot2.dict()],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery())

    repo.paginate.assert_called_once_with(limit=None, offset=None)
    assert result["total"] == 2
    assert len(result["items"]) == 2
    assert result["items"][0]["lot_number"] == "LOT-001"
    assert result["items"][1]["lot_number"] == "LOT-002"


def test_get_all_lots_empty():
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery())
    assert result["total"] == 0
    assert result["items"] == []


def test_get_lots_by_product():
    lot1 = _make_lot(id=1, lot_number="LOT-001")
    lot2 = _make_lot(id=2, lot_number="LOT-002")
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [lot1.dict(), lot2.dict()],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery(product_id=5))

    repo.paginate_by_spec.assert_called_once()
    assert result["total"] == 2
    assert len(result["items"]) == 2


def test_get_lots_by_product_empty():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery(product_id=99))
    assert result["total"] == 0
    assert result["items"] == []


def test_get_expiring_lots():
    expiry = date.today() + timedelta(days=10)
    lot = _make_lot(expiration_date=expiry, current_quantity=5)
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [lot.dict()],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery(expiring_in_days=30))

    repo.paginate_by_spec.assert_called_once()
    assert result["total"] == 1
    assert len(result["items"]) == 1


def test_get_expiring_lots_empty():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetAllLotsQueryHandler(repo)

    result = handler.handle(GetAllLotsQuery(expiring_in_days=30))
    assert result["total"] == 0
    assert result["items"] == []


# ---------------------------------------------------------------------------
# GetLotByIdQueryHandler
# ---------------------------------------------------------------------------


def test_get_lot_by_id():
    lot = _make_lot()
    repo = MagicMock()
    repo.get_by_id.return_value = lot
    handler = GetLotByIdQueryHandler(repo)

    result = handler.handle(GetLotByIdQuery(id=1))

    repo.get_by_id.assert_called_once_with(1)
    assert result["id"] == 1


def test_get_lot_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetLotByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetLotByIdQuery(id=99))
