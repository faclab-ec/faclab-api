"""Run the inventory report queries against an in-memory SQLite database.

The other report tests mock the aggregate rows, so they can't catch mistakes in
the SQL itself (e.g. the sign of OUT movements, which are stored negative).
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.reports.inventory.app.queries.rotation import (
    GetProductRotationQuery,
    GetProductRotationQueryHandler,
)
from src.reports.inventory.app.queries.valuation import (
    GetInventoryValuationQuery,
    GetInventoryValuationQueryHandler,
)
from src.shared.infra.database import Base

_TABLES = [
    Base.metadata.tables[model.__tablename__]
    for model in (
        CategoryModel,
        UnitOfMeasureModel,
        ProductModel,
        WarehouseModel,
        LocationModel,
        MovementModel,
        StockModel,
    )
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    db.add(
        ProductModel(
            id=1, name="Product A", sku="SKU-A", purchase_price=Decimal("10.00")
        )
    )
    db.add_all(
        [
            MovementModel(
                product_id=1,
                quantity=100,
                type=MovementType.IN,
                date=datetime(2026, 3, 1, 10),
            ),
            MovementModel(
                product_id=1,
                quantity=-30,
                type=MovementType.OUT,
                date=datetime(2026, 3, 10, 10),
            ),
            MovementModel(
                product_id=1,
                quantity=-20,
                type=MovementType.OUT,
                date=datetime(2026, 4, 5, 10),
            ),
        ]
    )
    db.add(StockModel(product_id=1, quantity=50))
    db.commit()
    yield db
    db.close()


def test_rotation_counts_out_movements_as_positive(session):
    handler = GetProductRotationQueryHandler(session)

    result = handler.handle(
        GetProductRotationQuery(from_date=date(2026, 3, 1), to_date=date(2026, 3, 31))
    )

    assert len(result) == 1
    assert result[0]["total_in"] == 100
    assert result[0]["total_out"] == 30
    assert result[0]["current_stock"] == 50
    assert result[0]["turnover_rate"] == Decimal("0.6")
    # 30 units out over 31 days, 50 in stock -> 51 days
    assert result[0]["days_of_stock"] == 51


def test_valuation_at_date_subtracts_out_movements(session):
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery(as_of_date=date(2026, 3, 31)))

    assert len(result["items"]) == 1
    assert result["items"][0]["quantity"] == 70
    assert result["items"][0]["total_value"] == Decimal("700.00")


def test_valuation_at_later_date_includes_all_movements(session):
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery(as_of_date=date(2026, 4, 30)))

    assert result["items"][0]["quantity"] == 50
