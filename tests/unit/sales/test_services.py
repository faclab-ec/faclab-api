from decimal import Decimal
from typing import Any

from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.services import recalculate_sale_totals
from src.shared.domain.tax import TaxCode


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_item(
    quantity=1,
    unit_price=Decimal("100"),
    discount=Decimal("0"),
    tax_code=TaxCode.VAT_12,
    **overrides,
) -> SaleItem:
    base = unit_price * quantity
    discount_amount = base * (discount / Decimal("100"))
    subtotal = base - discount_amount
    tax_amount = subtotal * tax_code.rate / Decimal("100")
    defaults: dict[str, Any] = {
        "sale_id": 1,
        "product_id": 100,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount": discount,
        "tax_code": tax_code,
        "tax_amount": tax_amount,
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


class TestRecalculateSaleTotals:
    def test_no_discount(self):
        """Totales sin descuento de venta"""
        sale = _make_sale()
        items = [
            _make_item(quantity=2, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12)
        ]
        # subtotal = 200, tax = 24, total = 224

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("200")
        assert sale.tax == Decimal("24")
        assert sale.discount == Decimal("0")
        assert sale.total == Decimal("224")

    def test_percentage_discount(self):
        """Descuento porcentual a nivel de venta"""
        sale = _make_sale(discount_type="PERCENTAGE", discount_value=Decimal("10"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12)
        ]
        # subtotal = 100, tax = 12, discount = 10, total = 102

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("100")
        assert sale.tax == Decimal("12")
        assert sale.discount == Decimal("10")
        assert sale.total == Decimal("102")

    def test_amount_discount(self):
        """Descuento de monto fijo a nivel de venta"""
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("25"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12)
        ]
        # subtotal = 100, tax = 12, discount = 25, total = 87

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("100")
        assert sale.tax == Decimal("12")
        assert sale.discount == Decimal("25")
        assert sale.total == Decimal("87")

    def test_mixed_tax_rates(self):
        """Items con distintos tax_rates (12% y 0%)"""
        sale = _make_sale()
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12),
            _make_item(
                quantity=1,
                unit_price=Decimal("50"),
                tax_code=TaxCode.VAT_0,
                product_id=200,
            ),
        ]
        # subtotal = 150, tax = 12 + 0 = 12, total = 162

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("150")
        assert sale.tax == Decimal("12")
        assert sale.total == Decimal("162")

    def test_no_items(self):
        """Sin items, totales en 0"""
        sale = _make_sale(discount_type="PERCENTAGE", discount_value=Decimal("10"))
        items = []

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("0")
        assert sale.tax == Decimal("0")
        assert sale.discount == Decimal("0")
        assert sale.total == Decimal("0")

    def test_item_with_discount(self):
        """Item con descuento a nivel de item + impuesto"""
        sale = _make_sale()
        items = [
            _make_item(
                quantity=2,
                unit_price=Decimal("100"),
                discount=Decimal("10"),
                tax_code=TaxCode.VAT_12,
            ),
        ]
        # base = 200, item discount = 20, subtotal = 180, tax = 21.6, total = 201.6

        recalculate_sale_totals(sale, items)

        assert sale.subtotal == Decimal("180")
        assert sale.tax == Decimal("21.6")
        assert sale.total == Decimal("201.6")
