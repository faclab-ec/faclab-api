"""Sale and refund lines in a presentation (S5.2): quantity and price of the
presentation, stock in base units."""

from decimal import Decimal

from src.catalog.product.domain.entities import Product, ProductPresentation
from src.invoicing.infra.event_handlers import line_name
from src.pos.refund.domain.entities import RefundItem
from src.pos.refund.infra.mappers import RefundItemMapper
from src.sales.domain.entities import SaleItem
from src.sales.domain.events import sale_items_data
from src.sales.infra.mappers import SaleItemMapper

BOXES = SaleItem(
    sale_id=1,
    product_id=10,
    quantity=Decimal(2),
    unit_price=Decimal("4.50"),
    presentation_id=7,
    unit_factor=Decimal(100),
)


def test_a_line_of_boxes_moves_its_units():
    assert BOXES.base_quantity == Decimal(200)
    # The money stays in the presentation
    assert BOXES.subtotal == Decimal("9.00")


def test_a_line_from_before_is_in_base_units():
    line = SaleItem(
        sale_id=1, product_id=10, quantity=Decimal(3), unit_price=Decimal(1)
    )

    assert (line.presentation_id, line.base_quantity) == (None, Decimal(3))


def test_the_mappers_store_the_base_quantity():
    assert SaleItemMapper().to_dict(BOXES)["base_quantity"] == Decimal(200)
    refund = RefundItem(
        refund_id=1,
        original_sale_item_id=1,
        product_id=10,
        quantity=Decimal(1),
        unit_price=Decimal("4.50"),
        presentation_id=7,
        unit_factor=Decimal(100),
    )
    assert RefundItemMapper().to_dict(refund)["base_quantity"] == Decimal(100)


def test_the_events_carry_both_quantities():
    [item] = sale_items_data([BOXES])

    assert (item["quantity"], item["base_quantity"], item["presentation_id"]) == (
        Decimal(2),
        Decimal(200),
        7,
    )


def test_the_invoice_line_names_a_presentation_other_than_the_unit():
    screw = Product(id=10, sku="TOR-1", name="Tornillo 1/2", unit_of_measure_id=1)
    base = ProductPresentation(product_id=10, name="Unidad", is_base=True)
    box = ProductPresentation(product_id=10, name="Caja x100", factor=Decimal(100))

    assert line_name(screw, box) == "Tornillo 1/2 (Caja x100)"
    assert line_name(screw, base) == "Tornillo 1/2"
    assert line_name(screw, None) == "Tornillo 1/2"
    assert line_name(None, box) is None
