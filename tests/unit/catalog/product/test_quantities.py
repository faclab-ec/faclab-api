from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest

from src.catalog.product.app.commands import (
    CreateProductCommand,
    CreateProductCommandHandler,
)
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.domain.entities import Product
from src.catalog.uom.domain.entities import UnitOfMeasure
from src.shared.domain.quantity import QuantityPrecisionError
from tests.audit import FakeAuditTrail
from tests.presentations import FakeProductPresentations

METER = UnitOfMeasure(id=2, name="Metro", symbol="m", decimals=2)
UNIT = UnitOfMeasure(id=1, name="Unidad", symbol="und", decimals=0)


def _quantities(*products: Product) -> ProductQuantities:
    product_repo = Mock()
    product_repo.get_by_ids.side_effect = lambda ids: [
        p for p in products if p.id in set(ids)
    ]
    unit_repo = Mock()
    unit_repo.get_by_ids.side_effect = lambda ids: [
        u for u in (METER, UNIT) if u.id in set(ids)
    ]
    return ProductQuantities(product_repo, unit_repo)


CABLE = Product(id=10, sku="CAB-1", name="Cable", unit_of_measure_id=METER.id)
HAMMER = Product(id=11, sku="MAR-1", name="Martillo", unit_of_measure_id=UNIT.id)
NO_UNIT = Product(id=12, sku="SIN-1", name="Sin unidad")


def test_each_product_takes_the_decimals_of_its_unit():
    quantities = _quantities(CABLE, HAMMER, NO_UNIT)

    assert quantities.decimals([10, 11, 12, 99]) == {10: 2, 11: 0, 12: 0}


def test_a_meter_takes_two_decimals():
    _quantities(CABLE).ensure([(10, Decimal("2.5")), (10, Decimal("1.25"))])

    with pytest.raises(QuantityPrecisionError, match="Product 10 takes at most 2"):
        _quantities(CABLE).ensure([(10, Decimal("1.255"))])


def test_a_unit_with_no_decimals_rejects_a_fraction():
    with pytest.raises(QuantityPrecisionError, match="Product 11 takes whole numbers"):
        _quantities(HAMMER).ensure([(11, Decimal("1.5"))])


def test_a_product_without_unit_takes_whole_numbers():
    _quantities(NO_UNIT).ensure([(12, Decimal("3.000000"))])

    with pytest.raises(QuantityPrecisionError):
        _quantities(NO_UNIT).ensure([(12, Decimal("0.5"))])


def test_an_unknown_product_is_left_to_its_handler():
    _quantities().ensure([(99, Decimal("0.123"))])


def test_products_are_described_with_their_unit():
    described = _quantities().describe(
        [
            {"id": 10, "unit_of_measure_id": 2},
            {"id": 12, "unit_of_measure_id": None},
        ]
    )

    assert [(p["unit_symbol"], p["quantity_decimals"]) for p in described] == [
        ("m", 2),
        (None, 0),
    ]


def _create_handler() -> CreateProductCommandHandler:
    repo = Mock()
    repo.create.side_effect = lambda product: replace(product, id=1)
    return CreateProductCommandHandler(
        repo, MagicMock(), FakeAuditTrail(), _quantities(), FakeProductPresentations()
    )


def test_stock_thresholds_take_the_decimals_of_the_unit():
    result = _create_handler().handle(
        CreateProductCommand(
            sku="CAB-2",
            name="Cable 12",
            unit_of_measure_id=METER.id,
            min_stock=Decimal("2.5"),
            reorder_point=Decimal("10.25"),
        )
    )

    assert result["min_stock"] == Decimal("2.5")
    assert (result["unit_symbol"], result["quantity_decimals"]) == ("m", 2)


def test_a_fractional_threshold_needs_a_unit_with_decimals():
    with pytest.raises(QuantityPrecisionError):
        _create_handler().handle(
            CreateProductCommand(
                sku="MAR-2",
                name="Martillo",
                unit_of_measure_id=UNIT.id,
                min_stock=Decimal("1.5"),
            )
        )
