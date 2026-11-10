"""Presentations of a product (S5.2): a box of 100 or a roll of 50 m, with a
decimal factor to the base unit, its own barcode and its own price."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.catalog.product.app.commands.presentations import (
    CreateProductPresentationCommand,
    CreateProductPresentationCommandHandler,
    DeleteProductPresentationCommand,
    DeleteProductPresentationCommandHandler,
    UpdateProductPresentationCommand,
    UpdateProductPresentationCommandHandler,
)
from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.catalog.product.domain.exceptions import (
    BasePresentationFixedError,
    InvalidPresentationFactorError,
    PresentationInactiveError,
)
from src.catalog.uom.domain.entities import UnitOfMeasure
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.quantity import QuantityPrecisionError, presentation_decimals
from tests.audit import FakeAuditTrail

UNIT = UnitOfMeasure(id=1, name="Unidad", symbol="und", decimals=0)
METER = UnitOfMeasure(id=2, name="Metro", symbol="m", decimals=2)
SCREW = Product(
    id=10,
    sku="TOR-1",
    name="Tornillo",
    unit_of_measure_id=UNIT.id,
    sale_price=Decimal("0.05"),
    purchase_price=Decimal("0.03"),
)
CABLE = Product(
    id=11,
    sku="CAB-1",
    name="Cable",
    unit_of_measure_id=METER.id,
    sale_price=Decimal("1.20"),
)
SCREW_BASE = ProductPresentation(
    id=100, product_id=10, name="Unidad", barcode="786100", is_base=True
)
BOX = ProductPresentation(
    id=101,
    product_id=10,
    name="Caja x100",
    factor=Decimal(100),
    barcode="786101",
    sale_price=Decimal("4.50"),
)


# Entity


@pytest.mark.parametrize("factor", [Decimal(0), Decimal(-1), Decimal("-0.5")])
def test_the_factor_cant_be_zero_or_negative(factor):
    with pytest.raises(InvalidPresentationFactorError, match="greater than zero"):
        ProductPresentation(product_id=10, name="Caja", factor=factor)


def test_a_bad_factor_answers_422():
    assert isinstance(InvalidPresentationFactorError(), ValidationError)


def test_the_base_presentation_is_the_unit_with_the_products_prices():
    with pytest.raises(BasePresentationFixedError):
        ProductPresentation(product_id=10, name="Caja", factor=Decimal(2), is_base=True)
    with pytest.raises(BasePresentationFixedError):
        ProductPresentation(
            product_id=10, name="Unidad", is_base=True, sale_price=Decimal(1)
        )


def test_a_quantity_in_a_presentation_in_base_units():
    assert BOX.base_quantity(Decimal(2)) == Decimal(200)
    roll = ProductPresentation(product_id=11, name="Rollo", factor=Decimal("50.5"))
    assert roll.base_quantity(Decimal("1.5")) == Decimal("75.75")


def test_its_own_price_or_factor_times_the_products():
    no_price = replace(BOX, sale_price=None)

    assert BOX.effective_sale_price(SCREW.sale_price) == Decimal("4.50")
    assert no_price.effective_sale_price(SCREW.sale_price) == Decimal("5.000000")
    assert no_price.effective_purchase_price(SCREW.purchase_price) == Decimal(
        "3.000000"
    )
    assert no_price.effective_sale_price(None) is None
    assert SCREW_BASE.effective_sale_price(SCREW.sale_price) == SCREW.sale_price


def test_only_the_barcode_of_the_base_changes():
    base = replace(SCREW_BASE)
    base.change(
        name="Unidad",
        factor=Decimal(1),
        barcode="786199",
        sale_price=None,
        purchase_price=None,
        is_active=True,
    )
    assert base.barcode == "786199"

    with pytest.raises(BasePresentationFixedError):
        base.change(
            name="Unidad",
            factor=Decimal(1),
            barcode="786199",
            sale_price=Decimal("0.10"),
            purchase_price=None,
            is_active=True,
        )
    with pytest.raises(BasePresentationFixedError):
        base.change(
            name="Unidad",
            factor=Decimal(1),
            barcode=None,
            sale_price=None,
            purchase_price=None,
            is_active=False,
        )


def test_a_change_keeps_the_factor_positive():
    box = replace(BOX)
    with pytest.raises(InvalidPresentationFactorError):
        box.change(
            name="Caja",
            factor=Decimal(0),
            barcode=None,
            sale_price=None,
            purchase_price=None,
            is_active=True,
        )


# Decimals


@pytest.mark.parametrize(
    ("unit_decimals", "factor", "expected"),
    [
        (0, Decimal(100), 0),  # box of 100 units
        (0, Decimal(1), 0),
        (2, Decimal(50), 2),  # roll of 50 m
        (2, Decimal("0.5"), 1),  # half a meter
        (3, Decimal("2.000"), 3),
        (2, Decimal("0.25"), 0),
    ],
)
def test_a_presentation_takes_the_decimals_of_its_unit_minus_its_factors(
    unit_decimals, factor, expected
):
    assert presentation_decimals(unit_decimals, factor) == expected


def _quantities() -> ProductQuantities:
    products = Mock()
    products.get_by_ids.side_effect = lambda ids: [
        p for p in (SCREW, CABLE) if p.id in set(ids)
    ]
    units = Mock()
    units.get_by_ids.side_effect = lambda ids: [
        u for u in (UNIT, METER) if u.id in set(ids)
    ]
    units.get_by_id.side_effect = lambda id: next(
        (u for u in (UNIT, METER) if u.id == id), None
    )
    return ProductQuantities(products, units)


def test_a_quantity_in_a_presentation_keeps_its_base_units_whole():
    quantities = _quantities()
    quantities.ensure_for_presentation(SCREW, Decimal(100), Decimal(2))
    quantities.ensure_for_presentation(CABLE, Decimal(50), Decimal("1.25"))

    with pytest.raises(QuantityPrecisionError, match="takes whole numbers"):
        quantities.ensure_for_presentation(SCREW, Decimal(100), Decimal("0.5"))
    with pytest.raises(QuantityPrecisionError, match="at most 1 decimal"):
        quantities.ensure_for_presentation(CABLE, Decimal("0.5"), Decimal("0.25"))


def test_lines_in_a_presentation_keep_their_base_units_whole():
    quantities = _quantities()
    quantities.ensure_in_presentations(
        [(10, Decimal(100), Decimal(1)), (11, Decimal(50), Decimal("0.5"))]
    )

    with pytest.raises(QuantityPrecisionError, match="Product 10 takes whole"):
        quantities.ensure_in_presentations([(10, Decimal(100), Decimal("0.5"))])
    # An unknown product is left to its handler
    quantities.ensure_in_presentations([(99, Decimal(3), Decimal("0.123"))])


# The service


def _of(presentations, product_ids: set[int]) -> list[ProductPresentation]:
    return [p for p in presentations if p.product_id in product_ids]


def _service(*presentations: ProductPresentation) -> ProductPresentations:
    repo = Mock()
    rows = {p.id: p for p in presentations}
    repo.get_by_id.side_effect = rows.get
    repo.get_by_ids.side_effect = lambda ids: [rows[i] for i in ids if i in rows]
    repo.base_of.side_effect = lambda product_id: next(
        (p for p in rows.values() if p.product_id == product_id and p.is_base), None
    )
    repo.by_barcode.side_effect = lambda code: next(
        (p for p in rows.values() if p.barcode == code), None
    )
    repo.for_products.side_effect = lambda ids: _of(rows.values(), set(ids))
    repo.create.side_effect = lambda p: replace(p, id=999)
    repo.update.side_effect = lambda p: p
    products = Mock()
    products.get_by_id.side_effect = {SCREW.id: SCREW, CABLE.id: CABLE}.get
    units = Mock()
    units.get_by_id.side_effect = {UNIT.id: UNIT, METER.id: METER}.get
    return ProductPresentations(repo, products, units)


def test_a_line_without_presentation_is_of_the_base_one():
    assert _service(SCREW_BASE, BOX).resolve(SCREW, None) == SCREW_BASE


def test_a_line_takes_a_presentation_of_its_product():
    service = _service(SCREW_BASE, BOX)

    assert service.resolve(SCREW, BOX.id) == BOX
    with pytest.raises(NotFoundError):
        service.resolve(CABLE, BOX.id)
    with pytest.raises(NotFoundError):
        service.resolve(SCREW, 555)


def test_an_inactive_presentation_isnt_sold():
    service = _service(replace(BOX, is_active=False))

    with pytest.raises(PresentationInactiveError):
        service.resolve(SCREW, BOX.id)


def test_the_base_presentation_is_named_after_the_unit():
    service = _service()

    base = service.create_base(CABLE, "786200")

    assert (base.name, base.factor, base.barcode, base.is_base) == (
        "Metro",
        Decimal(1),
        "786200",
        True,
    )


def test_the_base_follows_the_unit_and_the_barcode():
    service = _service(replace(SCREW_BASE))

    base = service.sync_base(replace(SCREW, unit_of_measure_id=METER.id), "786150")

    assert (base.name, base.barcode) == ("Metro", "786150")


def test_a_scanned_barcode_finds_the_product_and_its_presentation():
    service = _service(SCREW_BASE, BOX)

    assert service.by_barcode("786101") == (SCREW, BOX)
    assert service.by_barcode("000") is None


def test_an_inactive_presentation_isnt_found_by_barcode():
    assert _service(replace(BOX, is_active=False)).by_barcode("786101") is None


def test_products_are_described_with_barcode_and_presentations():
    [described] = _service(SCREW_BASE, BOX).describe(
        [{"id": 10, "sale_price": Decimal("0.05"), "quantity_decimals": 0}]
    )

    assert described["barcode"] == "786100"
    base, box = described["presentations"]
    assert (base["is_base"], base["effective_sale_price"]) == (True, Decimal("0.05"))
    assert (box["name"], box["effective_sale_price"], box["quantity_decimals"]) == (
        "Caja x100",
        Decimal("4.50"),
        0,
    )


# Commands


def _repo(*presentations: ProductPresentation) -> Mock:
    repo = Mock()
    rows = {p.id: p for p in presentations}
    repo.get_by_id.side_effect = rows.get
    repo.create.side_effect = lambda p: replace(p, id=200)
    repo.update.side_effect = lambda p: p
    return repo


def _products() -> Mock:
    products = Mock()
    products.get_by_id.side_effect = {SCREW.id: SCREW, CABLE.id: CABLE}.get
    return products


def test_a_presentation_is_added_and_audited():
    audit = FakeAuditTrail()
    handler = CreateProductPresentationCommandHandler(
        _products(), _repo(), _quantities(), audit
    )

    result = handler.handle(
        CreateProductPresentationCommand(
            product_id=10, name="Caja x100", factor=Decimal(100), barcode="786101"
        )
    )

    assert (result["id"], result["effective_sale_price"]) == (200, Decimal("5.000000"))
    (entry,) = audit.entries
    assert entry.action == AuditAction.PRODUCT_PRESENTATION_CREATED
    assert entry.resource_id == 10
    assert entry.after is not None
    assert entry.after["factor"] == Decimal(100)


def test_a_factor_must_fit_the_unit():
    handler = CreateProductPresentationCommandHandler(
        _products(), _repo(), _quantities(), FakeAuditTrail()
    )

    with pytest.raises(QuantityPrecisionError):
        handler.handle(
            CreateProductPresentationCommand(
                product_id=10, name="Media caja", factor=Decimal("2.5")
            )
        )


def test_a_presentation_of_an_unknown_product_is_not_found():
    handler = CreateProductPresentationCommandHandler(
        _products(), _repo(), _quantities(), FakeAuditTrail()
    )

    with pytest.raises(NotFoundError):
        handler.handle(
            CreateProductPresentationCommand(
                product_id=99, name="Caja", factor=Decimal(10)
            )
        )


def test_an_update_audits_only_what_changed():
    audit = FakeAuditTrail()
    handler = UpdateProductPresentationCommandHandler(
        _products(), _repo(replace(BOX)), _quantities(), audit
    )

    handler.handle(
        UpdateProductPresentationCommand(
            product_id=10,
            presentation_id=BOX.require_id(),
            name=BOX.name,
            factor=BOX.factor,
            barcode=BOX.barcode,
            sale_price=Decimal("4.80"),
        )
    )

    (entry,) = audit.entries
    assert entry.action == AuditAction.PRODUCT_PRESENTATION_UPDATED
    assert entry.before == {
        "presentation_id": BOX.id,
        "name": "Caja x100",
        "sale_price": Decimal("4.50"),
    }
    assert entry.after == {
        "presentation_id": BOX.id,
        "name": "Caja x100",
        "sale_price": Decimal("4.80"),
    }


def test_an_update_that_changes_nothing_leaves_no_entry():
    audit = FakeAuditTrail()
    UpdateProductPresentationCommandHandler(
        _products(), _repo(replace(BOX)), _quantities(), audit
    ).handle(
        UpdateProductPresentationCommand(
            product_id=10,
            presentation_id=BOX.require_id(),
            name=BOX.name,
            factor=BOX.factor,
            barcode=BOX.barcode,
            sale_price=BOX.sale_price,
        )
    )

    assert audit.entries == []


def test_a_presentation_of_another_product_is_not_found():
    handler = UpdateProductPresentationCommandHandler(
        _products(), _repo(replace(BOX)), _quantities(), FakeAuditTrail()
    )

    with pytest.raises(NotFoundError):
        handler.handle(
            UpdateProductPresentationCommand(
                product_id=11,
                presentation_id=BOX.require_id(),
                name="Caja",
                factor=Decimal(10),
            )
        )


def test_the_base_presentation_isnt_deleted():
    handler = DeleteProductPresentationCommandHandler(
        _repo(SCREW_BASE), FakeAuditTrail()
    )

    with pytest.raises(BasePresentationFixedError, match="can't be deleted"):
        handler.handle(
            DeleteProductPresentationCommand(
                product_id=10, presentation_id=SCREW_BASE.require_id()
            )
        )


def test_a_deleted_presentation_is_audited():
    audit = FakeAuditTrail()
    repo = _repo(BOX)

    DeleteProductPresentationCommandHandler(repo, audit).handle(
        DeleteProductPresentationCommand(
            product_id=10, presentation_id=BOX.require_id()
        )
    )

    repo.delete.assert_called_once_with(BOX.id)
    assert audit.actions == [AuditAction.PRODUCT_PRESENTATION_DELETED]


def test_a_product_built_from_a_request_may_carry_float_prices():
    # model_dump() of a DecimalNumber gives a float
    no_price = replace(BOX, sale_price=None)

    assert no_price.effective_sale_price(0.05) == Decimal("5.000000")
