"""The valued kardex and the valuation at real cost (S5.6), on in-memory SQLite.

Product 1 in warehouse 1 (locations 1 and 2) and warehouse 2 (location 3):

- 03-01  IN  10 at 5.00 (purchase)          loc 1
- 03-05  IN  30 at 7.00 (purchase)          loc 1   average 6.50
- 03-10  OUT 15 at 6.50 (sale)              loc 1
- 04-02  OUT  5 at 6.50 (transfer)          loc 1
- 04-02  IN   5 at 6.50 (transfer)          loc 3
- 04-03  IN 2.5 at 8.00 (initial balance)   loc 2

The costs are exact in binary, so SQLite's float sums don't round them.
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from src.catalog.product.infra.models import CategoryModel, ProductModel
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.reports.inventory.app.queries.kardex import (
    GetKardexQuery,
    GetKardexQueryHandler,
)
from src.reports.inventory.app.queries.valuation import (
    GetInventoryValuationQuery,
    GetInventoryValuationQueryHandler,
)
from src.reports.inventory.app.queries.warehouse_summary import (
    GetWarehouseSummaryQuery,
    GetWarehouseSummaryQueryHandler,
)
from src.shared.domain.exceptions import NotFoundError
from tests.sqlite import sqlite_session

_MODELS = (
    CategoryModel,
    UnitOfMeasureModel,
    ProductModel,
    WarehouseModel,
    LocationModel,
    MovementModel,
    StockModel,
)


def _movement(
    when: str, quantity: str, cost: str, location: int, reference: str, product=1
):
    return MovementModel(
        product_id=product,
        quantity=Decimal(quantity),
        type=MovementType.IN if Decimal(quantity) > 0 else MovementType.OUT,
        unit_cost=Decimal(cost),
        location_id=location,
        reference_type=reference,
        reference_id=1,
        date=datetime.fromisoformat(f"2026-{when}T10:00:00"),
    )


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(_MODELS)
    db.add_all(
        [
            ProductModel(
                id=1,
                name="Cemento",
                sku="CEM-50",
                purchase_price=Decimal("5.00"),
                unit_of_measure_id=1,
            ),
            ProductModel(id=2, name="Clavo", sku="CLV-1", unit_of_measure_id=1),
            WarehouseModel(id=1, branch_id=1, name="Matriz", code="BOD-001"),
            WarehouseModel(id=2, branch_id=1, name="Norte", code="BOD-002"),
            LocationModel(id=1, warehouse_id=1, name="Percha", code="A1"),
            LocationModel(id=2, warehouse_id=1, name="Bodega", code="B1"),
            LocationModel(id=3, warehouse_id=2, name="General", code="G1"),
        ]
    )
    db.add_all(
        [
            _movement("03-01", "10", "5.00", 1, "purchase_order"),
            _movement("03-05", "30", "7.00", 1, "purchase_order"),
            _movement("03-10", "-15", "6.50", 1, "sale"),
            _movement("04-02", "-5", "6.50", 1, "transfer"),
            _movement("04-02", "5", "6.50", 3, "transfer"),
            _movement("04-03", "2.5", "8.00", 2, "adjustment"),
            # Another product doesn't enter its kardex
            _movement("03-02", "100", "0.10", 1, "purchase_order", product=2),
        ]
    )
    db.add_all(
        [
            StockModel(
                product_id=1, location_id=1, quantity=20, average_cost=Decimal("6.5")
            ),
            StockModel(
                product_id=1, location_id=2, quantity=2.5, average_cost=Decimal("8")
            ),
            StockModel(
                product_id=1, location_id=3, quantity=5, average_cost=Decimal("6.5")
            ),
            StockModel(
                product_id=2, location_id=1, quantity=100, average_cost=Decimal("0.1")
            ),
        ]
    )
    db.commit()
    yield db
    db.close()


def _kardex(session, **kwargs) -> dict:
    return GetKardexQueryHandler(session).handle(GetKardexQuery(product_id=1, **kwargs))


def test_the_kardex_of_a_warehouse_adds_up_in_quantity_and_value(session):
    kardex = _kardex(
        session,
        warehouse_id=1,
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
    )

    # Before April: 10 × 5.00 + 30 × 7.00 − 15 × 6.50
    assert kardex["opening"] == {
        "quantity": Decimal(25),
        "value": Decimal("162.50"),
        "average_cost": Decimal("6.50"),
    }
    rows = [
        (
            e["type"],
            e["in_quantity"],
            e["out_quantity"],
            e["unit_cost"],
            e["value"],
            e["balance_quantity"],
            e["balance_value"],
            e["average_cost"],
        )
        for e in kardex["entries"]
    ]
    assert rows == [
        (
            "OUT",
            0,
            5,
            Decimal("6.5"),
            Decimal("32.5"),
            20,
            Decimal("130"),
            Decimal("6.5"),
        ),
        (
            "IN",
            2.5,
            0,
            Decimal("8"),
            Decimal("20"),
            22.5,
            Decimal("150"),
            Decimal("6.666667"),
        ),
    ]
    assert kardex["total_in"] == {"quantity": Decimal("2.5"), "value": Decimal("20")}
    assert kardex["total_out"] == {"quantity": Decimal(5), "value": Decimal("32.5")}
    closing = kardex["closing"]
    assert (closing["quantity"], closing["value"]) == (Decimal("22.5"), Decimal(150))
    # Closing = opening + entries − exits, in quantity and in value
    assert closing["quantity"] == (
        kardex["opening"]["quantity"]
        + kardex["total_in"]["quantity"]
        - kardex["total_out"]["quantity"]
    )
    assert closing["value"] == (
        kardex["opening"]["value"]
        + kardex["total_in"]["value"]
        - kardex["total_out"]["value"]
    )


def test_the_closing_balance_is_the_valuation_of_the_warehouse(session):
    kardex = _kardex(
        session, warehouse_id=1, from_date=date(2026, 3, 1), to_date=date(2026, 12, 31)
    )
    valuation = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery(warehouse_id=1)
    )

    [item] = [i for i in valuation["items"] if i["product_id"] == 1]
    assert kardex["opening"]["quantity"] == 0
    assert (item["quantity"], item["total_value"]) == (
        kardex["closing"]["quantity"],
        kardex["closing"]["value"],
    )
    # Weighted across its two locations: 150.00 / 22.5
    assert item["average_cost"] == Decimal("6.666667")


def test_a_transfer_between_warehouses_carries_its_cost(session):
    kardex = _kardex(
        session, warehouse_id=2, from_date=date(2026, 3, 1), to_date=date(2026, 12, 31)
    )

    [entry] = kardex["entries"]
    assert (entry["reference_type"], entry["location_name"]) == ("transfer", "General")
    assert (entry["in_quantity"], entry["unit_cost"]) == (5, Decimal("6.5"))
    assert kardex["closing"]["value"] == Decimal("32.5")


def test_without_a_warehouse_it_takes_every_location(session):
    kardex = _kardex(session, from_date=date(2026, 3, 1), to_date=date(2026, 3, 31))

    assert [e["movement_id"] for e in kardex["entries"]] == [1, 2, 3]
    assert kardex["closing"] == {
        "quantity": Decimal(25),
        "value": Decimal("162.50"),
        "average_cost": Decimal("6.50"),
    }
    assert (kardex["product_name"], kardex["sku"]) == ("Cemento", "CEM-50")


def test_an_empty_balance_has_no_average(session):
    kardex = _kardex(
        session, warehouse_id=2, from_date=date(2026, 3, 1), to_date=date(2026, 3, 31)
    )

    assert kardex["entries"] == []
    assert kardex["opening"]["average_cost"] is None
    assert kardex["closing"] == {
        "quantity": 0,
        "value": 0,
        "average_cost": None,
    }


def test_an_unknown_product_or_warehouse_is_not_found(session):
    with pytest.raises(NotFoundError):
        GetKardexQueryHandler(session).handle(GetKardexQuery(product_id=99))
    with pytest.raises(NotFoundError):
        _kardex(session, warehouse_id=99)


def test_the_valuation_at_a_date_takes_the_cost_each_movement_had(session):
    valuation = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery(as_of_date=date(2026, 3, 31))
    )

    [item] = [i for i in valuation["items"] if i["product_id"] == 1]
    assert (item["quantity"], item["average_cost"], item["total_value"]) == (
        25,
        Decimal("6.50"),
        Decimal("162.50"),
    )


def test_the_current_valuation_weighs_the_average_of_each_location(session):
    valuation = GetInventoryValuationQueryHandler(session).handle(
        GetInventoryValuationQuery()
    )

    by_product = {i["product_id"]: i for i in valuation["items"]}
    # 20 × 6.50 + 2.5 × 8.00 + 5 × 6.50 = 182.50 over 27.5
    assert by_product[1]["total_value"] == Decimal("182.5")
    assert by_product[1]["average_cost"] == Decimal("6.636364")
    # A product without purchase price is valued at its own cost
    assert by_product[2]["total_value"] == Decimal("10")
    assert valuation["total_value"] == Decimal("192.5")


def test_the_warehouse_summary_values_at_average_cost(session):
    summary = GetWarehouseSummaryQueryHandler(session).handle(
        GetWarehouseSummaryQuery()
    )

    values = {row["warehouse_id"]: row["total_value"] for row in summary}
    assert values == {1: Decimal("160"), 2: Decimal("32.5")}
