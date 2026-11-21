from decimal import Decimal

import pytest

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.movement.infra.mappers import MovementMapper
from src.inventory.movement.infra.metrics import movement_source, stock_attempt
from src.inventory.movement.infra.models import MovementModel
from src.inventory.movement.infra.repositories import SqlAlchemyMovementRepository
from src.inventory.stock.domain.exceptions import InsufficientStockError
from src.shared.domain.exceptions import NotFoundError
from tests.sqlite import sqlite_session

pytestmark = pytest.mark.usefixtures("in_tenant")


def test_the_source_is_the_document_bounded():
    assert movement_source("sale") == "sale"
    assert movement_source("purchase_order") == "purchase_order"
    assert movement_source(None) == "manual"
    # A document type nobody listed yet doesn't open a new series
    assert movement_source("whatever_comes_next") == "other"


def _movement(quantity: str, reference_type: str | None) -> Movement:
    amount = Decimal(quantity)
    return Movement(
        product_id=1,
        quantity=amount,
        type=MovementType.IN if amount > 0 else MovementType.OUT,
        location_id=1,
        reference_type=reference_type,
        reference_id=1 if reference_type else None,
    )


def test_a_movement_counts_once_its_transaction_commits(recorded_metrics):
    session = sqlite_session([MovementModel])
    repo = SqlAlchemyMovementRepository(session, MovementMapper())

    repo.create(_movement("-2", "sale"))
    repo.create(_movement("5", None))
    assert recorded_metrics.collect().total("faclab.inventory.movements") == 0
    session.commit()

    points = recorded_metrics.collect().points("faclab.inventory.movements")
    assert sorted(points, key=str) == [
        (1, {"faclab.movement.type": "in", "faclab.movement.source": "manual"}),
        (1, {"faclab.movement.type": "out", "faclab.movement.source": "sale"}),
    ]


def test_a_rolled_back_movement_is_not_counted(recorded_metrics):
    session = sqlite_session([MovementModel])
    repo = SqlAlchemyMovementRepository(session, MovementMapper())

    repo.create(_movement("-2", "adjustment"))
    session.rollback()

    assert recorded_metrics.collect().total("faclab.inventory.movements") == 0


def test_stock_attempt_counts_only_insufficient_stock(recorded_metrics):
    with pytest.raises(InsufficientStockError), stock_attempt("transfer"):
        raise InsufficientStockError(1, Decimal(3))
    with pytest.raises(NotFoundError), stock_attempt("transfer"):
        raise NotFoundError("Transfer 9 not found")

    assert recorded_metrics.collect().points("faclab.inventory.stock_rejections") == [
        (1, {"faclab.movement.source": "transfer"})
    ]
