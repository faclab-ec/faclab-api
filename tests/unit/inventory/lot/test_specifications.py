from datetime import date, timedelta
from typing import Any

from src.inventory.lot.domain.entities import Lot
from src.inventory.lot.domain.specifications import (
    ExpiredLots,
    ExpiringLots,
    LotsByProduct,
)


def _make_lot(**overrides) -> Lot:
    defaults: dict[str, Any] = {
        "id": 1,
        "product_id": 5,
        "lot_number": "LOT-001",
        "initial_quantity": 100,
        "current_quantity": 50,
    }
    defaults.update(overrides)
    return Lot(**defaults)


# ---------------------------------------------------------------------------
# LotsByProduct
# ---------------------------------------------------------------------------


def test_lots_by_product_matches():
    lot = _make_lot(product_id=5)
    spec = LotsByProduct(product_id=5)
    assert spec.is_satisfied_by(lot) is True


def test_lots_by_product_not_matches():
    lot = _make_lot(product_id=5)
    spec = LotsByProduct(product_id=99)
    assert spec.is_satisfied_by(lot) is False


# ---------------------------------------------------------------------------
# ExpiringLots
# ---------------------------------------------------------------------------


def test_expiring_lots_matches_within_days():
    expiry = date.today() + timedelta(days=10)
    lot = _make_lot(expiration_date=expiry, current_quantity=5)
    spec = ExpiringLots(days=30)
    assert spec.is_satisfied_by(lot) is True


def test_expiring_lots_matches_boundary():
    expiry = date.today() + timedelta(days=30)
    lot = _make_lot(expiration_date=expiry, current_quantity=5)
    spec = ExpiringLots(days=30)
    assert spec.is_satisfied_by(lot) is True


def test_expiring_lots_not_matches_far_future():
    expiry = date.today() + timedelta(days=60)
    lot = _make_lot(expiration_date=expiry, current_quantity=5)
    spec = ExpiringLots(days=30)
    assert spec.is_satisfied_by(lot) is False


def test_expiring_lots_not_matches_no_expiration():
    lot = _make_lot(expiration_date=None, current_quantity=5)
    spec = ExpiringLots(days=30)
    assert spec.is_satisfied_by(lot) is False


def test_expiring_lots_not_matches_zero_quantity():
    expiry = date.today() + timedelta(days=10)
    lot = _make_lot(expiration_date=expiry, current_quantity=0)
    spec = ExpiringLots(days=30)
    assert spec.is_satisfied_by(lot) is False


# ---------------------------------------------------------------------------
# ExpiredLots
# ---------------------------------------------------------------------------


def test_expired_lots_matches_past_date():
    past = date.today() - timedelta(days=1)
    lot = _make_lot(expiration_date=past)
    spec = ExpiredLots()
    assert spec.is_satisfied_by(lot) is True


def test_expired_lots_not_matches_future_date():
    future = date.today() + timedelta(days=10)
    lot = _make_lot(expiration_date=future)
    spec = ExpiredLots()
    assert spec.is_satisfied_by(lot) is False


def test_expired_lots_not_matches_no_expiration():
    lot = _make_lot(expiration_date=None)
    spec = ExpiredLots()
    assert spec.is_satisfied_by(lot) is False


def test_expired_lots_not_matches_today():
    # today is NOT < today
    lot = _make_lot(expiration_date=date.today())
    spec = ExpiredLots()
    assert spec.is_satisfied_by(lot) is False
