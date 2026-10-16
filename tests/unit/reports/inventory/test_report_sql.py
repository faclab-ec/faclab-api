"""Run the inventory report queries against an in-memory SQLite database.

The other report tests mock the aggregate rows, so they can't catch mistakes in
the SQL itself (e.g. the sign of OUT movements, which are stored negative).
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

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
from src.reports.inventory.app.queries.warehouse_summary import (
    GetWarehouseSummaryQuery,
    GetWarehouseSummaryQueryHandler,
)
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session

OTHER_TENANT = UUID("00000000-0000-4000-8000-0000000000b2")

_MODELS = (
    CategoryModel,
    UnitOfMeasureModel,
    ProductModel,
    WarehouseModel,
    LocationModel,
    MovementModel,
    StockModel,
)


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(_MODELS)
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


@pytest.fixture
def other_tenant_stock(session):
    """Another tenant with the same SKU, stock and movements in its own warehouse"""
    session.add(TenantModel(id=OTHER_TENANT, ruc="0999999999001", legal_name="B"))
    session.commit()
    with use_tenant(TenantContext(OTHER_TENANT, TenantSource.TASK)):
        session.add(WarehouseModel(id=2, name="B", code="WH-01"))
        session.add(LocationModel(id=2, warehouse_id=2, name="B", code="A1"))
        session.add(
            ProductModel(
                id=2, name="Product A", sku="SKU-A", purchase_price=Decimal("99.00")
            )
        )
        session.add(
            MovementModel(
                product_id=2,
                location_id=2,
                quantity=500,
                type=MovementType.IN,
                date=datetime(2026, 3, 2, 10),
            )
        )
        session.add(StockModel(product_id=2, location_id=2, quantity=500))
        session.commit()


def test_reports_only_read_the_context_tenant(session, other_tenant_stock):
    rotation = GetProductRotationQueryHandler(session).handle(
        GetProductRotationQuery(from_date=date(2026, 3, 1), to_date=date(2026, 3, 31))
    )
    current = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery()
    )
    at_date = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery(as_of_date=date(2026, 3, 31))
    )
    summary = GetWarehouseSummaryQueryHandler(session).handle(
        GetWarehouseSummaryQuery()
    )

    assert [row["product_id"] for row in rotation] == [1]
    assert [item["product_id"] for item in current["items"]] == [1]
    assert [item["product_id"] for item in at_date["items"]] == [1]
    assert summary == []


def test_another_tenants_warehouse_filters_out_everything(session, other_tenant_stock):
    rotation = GetProductRotationQueryHandler(session).handle(
        GetProductRotationQuery(
            from_date=date(2026, 3, 1), to_date=date(2026, 3, 31), warehouse_id=2
        )
    )
    valuation = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery(as_of_date=date(2026, 3, 31), warehouse_id=2)
    )

    assert rotation == []
    assert valuation["items"] == []
