from decimal import Decimal
from typing import Any

from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.services import (
    InvoiceLine,
    SaleLine,
    discount_factor,
    invoice_lines,
    tax_breakdown,
)
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


class TestSaleRecalculateTotals:
    def test_no_discount(self):
        """Totales sin descuento de venta"""
        sale = _make_sale()
        items = [
            _make_item(quantity=2, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12)
        ]
        # subtotal = 200, tax = 24, total = 224

        sale.recalculate_totals(items)

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
        # subtotal = 100, discount = 10, tax = 12% of 90 = 10.8, total = 100.8

        sale.recalculate_totals(items)

        assert sale.subtotal == Decimal("100")
        assert sale.discount == Decimal("10")
        assert sale.tax == Decimal("10.8")
        assert sale.total == Decimal("100.8")

    def test_amount_discount(self):
        """Descuento de monto fijo a nivel de venta"""
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("25"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_12)
        ]
        # subtotal = 100, discount = 25, tax = 12% of 75 = 9, total = 84

        sale.recalculate_totals(items)

        assert sale.subtotal == Decimal("100")
        assert sale.discount == Decimal("25")
        assert sale.tax == Decimal("9")
        assert sale.total == Decimal("84")

    def test_discount_is_prorated_across_tax_rates(self):
        """El descuento global reduce la base de cada item en proporción a su subtotal"""
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("30"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_15),
            _make_item(
                quantity=1,
                unit_price=Decimal("50"),
                tax_code=TaxCode.VAT_0,
                product_id=200,
            ),
        ]
        # factor = 120/150 = 0.8 → taxed base 80, tax = 12; exempt base 40, tax = 0

        sale.recalculate_totals(items)

        assert sale.subtotal == Decimal("150")
        assert sale.discount == Decimal("30")
        assert sale.tax == Decimal("12")
        assert sale.total == Decimal("132")

    def test_amount_discount_is_capped_at_subtotal(self):
        """Un descuento mayor al subtotal no deja la venta en negativo"""
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("500"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_15)
        ]

        sale.recalculate_totals(items)

        assert sale.discount == Decimal("100")
        assert sale.tax == Decimal("0")
        assert sale.total == Decimal("0")

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

        sale.recalculate_totals(items)

        assert sale.subtotal == Decimal("150")
        assert sale.tax == Decimal("12")
        assert sale.total == Decimal("162")

    def test_no_items(self):
        """Sin items, totales en 0"""
        sale = _make_sale(discount_type="PERCENTAGE", discount_value=Decimal("10"))
        items = []

        sale.recalculate_totals(items)

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

        sale.recalculate_totals(items)

        assert sale.subtotal == Decimal("180")
        assert sale.tax == Decimal("21.6")
        assert sale.total == Decimal("201.6")

    def test_totals_are_rounded_to_cents(self):
        """Las líneas conservan su precisión; la venta se redondea al centavo"""
        sale = _make_sale()
        items = [
            _make_item(quantity=3, unit_price=Decimal("0.15"), tax_code=TaxCode.VAT_15)
        ]
        # subtotal = 0.45, tax = 0.0675 -> 0.07, total = 0.52

        sale.recalculate_totals(items)

        assert items[0].tax_amount == Decimal("0.0675")
        assert (sale.subtotal, sale.tax, sale.total) == (
            Decimal("0.45"),
            Decimal("0.07"),
            Decimal("0.52"),
        )

    def test_percentage_discount_is_rounded_and_total_adds_up(self):
        sale = _make_sale(discount_type="PERCENTAGE", discount_value=Decimal("3.33"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("10.00"), tax_code=TaxCode.VAT_15)
        ]
        # discount = 0.333 -> 0.33; tax = 1.5 * 9.67/10 = 1.4505 -> 1.45

        sale.recalculate_totals(items)

        assert sale.discount == Decimal("0.33")
        assert sale.tax == Decimal("1.45")
        assert (
            sale.total == sale.subtotal - sale.discount + sale.tax == Decimal("11.12")
        )

    def test_tax_is_rounded_per_tax_code(self):
        """Cada código de IVA se redondea por separado, como en la factura"""
        sale = _make_sale()
        items = [
            _make_item(quantity=1, unit_price=Decimal("0.10"), tax_code=TaxCode.VAT_5),
            _make_item(
                quantity=1,
                unit_price=Decimal("0.10"),
                tax_code=TaxCode.VAT_15,
                product_id=200,
            ),
        ]
        # 0.005 -> 0.01 and 0.015 -> 0.02; rounding the sum (0.02) would differ

        sale.recalculate_totals(items)

        assert sale.tax == Decimal("0.03")
        assert sale.total == Decimal("0.23")


class TestTaxBreakdown:
    def test_groups_by_tax_code_and_applies_the_discount_factor(self):
        lines = [
            (TaxCode.VAT_15, Decimal("100"), Decimal("15")),
            (TaxCode.VAT_15, Decimal("20"), Decimal("3")),
            (TaxCode.VAT_0, Decimal("30"), Decimal("0")),
        ]

        breakdown = tax_breakdown(lines, discount_factor(Decimal("150"), Decimal("15")))

        assert breakdown == {
            TaxCode.VAT_15: (Decimal("108.00"), Decimal("16.20")),
            TaxCode.VAT_0: (Decimal("27.00"), Decimal("0.00")),
        }

    def test_discount_factor_without_subtotal_is_one(self):
        assert discount_factor(Decimal("0"), Decimal("0")) == Decimal("1")


def _line(item: SaleItem) -> SaleLine:
    return SaleLine(
        gross=item.unit_price * item.quantity,
        tax_code=item.tax_code,
        subtotal=item.subtotal,
        tax_amount=item.tax_amount,
    )


def _invoice(sale: Sale, items: list[SaleItem]) -> list[InvoiceLine]:
    sale.recalculate_totals(items)
    return invoice_lines(
        [_line(item) for item in items], sale.subtotal, sale.discount, sale.tax
    )


class TestInvoiceLines:
    def test_without_discount_each_line_keeps_its_own_amounts(self):
        sale = _make_sale()
        items = [
            _make_item(quantity=2, unit_price=Decimal("10"), tax_code=TaxCode.VAT_15),
            _make_item(quantity=1, unit_price=Decimal("5"), tax_code=TaxCode.VAT_0),
        ]

        lines = _invoice(sale, items)

        assert lines == [
            InvoiceLine(Decimal("0.00"), Decimal("20.00"), Decimal("3.00")),
            InvoiceLine(Decimal("0.00"), Decimal("5.00"), Decimal("0.00")),
        ]

    def test_global_discount_is_prorated_into_each_line(self):
        sale = _make_sale(discount_type="PERCENTAGE", discount_value=Decimal("10"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("100"), tax_code=TaxCode.VAT_15),
            _make_item(quantity=1, unit_price=Decimal("50"), tax_code=TaxCode.VAT_0),
        ]

        lines = _invoice(sale, items)

        # 10% de 150 = 15: 10 a la primera línea y 5 a la segunda
        assert lines == [
            InvoiceLine(Decimal("10.00"), Decimal("90.00"), Decimal("13.50")),
            InvoiceLine(Decimal("5.00"), Decimal("45.00"), Decimal("0.00")),
        ]

    def test_line_discount_and_global_discount_add_up(self):
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("8"))
        items = [
            _make_item(
                quantity=2,
                unit_price=Decimal("50"),
                discount=Decimal("20"),
                tax_code=TaxCode.VAT_15,
            )
        ]

        [line] = _invoice(sale, items)

        # 100 bruto - 20 de la línea - 8 global = 72 de base
        assert line == InvoiceLine(Decimal("28.00"), Decimal("72.00"), Decimal("10.80"))

    def test_lines_add_up_to_the_sale_totals_when_cents_do_not_divide(self):
        sale = _make_sale(discount_type="AMOUNT", discount_value=Decimal("1"))
        items = [
            _make_item(quantity=1, unit_price=Decimal("3.33"), tax_code=TaxCode.VAT_15)
            for _ in range(3)
        ] + [
            _make_item(quantity=3, unit_price=Decimal("0.333"), tax_code=TaxCode.VAT_5),
            _make_item(quantity=1, unit_price=Decimal("2.10"), tax_code=TaxCode.EXEMPT),
        ]

        lines = _invoice(sale, items)

        bases = sum((line.taxable_base for line in lines), Decimal("0"))
        taxes = sum((line.tax for line in lines), Decimal("0"))
        assert bases == sale.subtotal - sale.discount
        assert taxes == sale.tax
        assert bases + taxes == sale.total
        breakdown = tax_breakdown(
            ((i.tax_code, i.subtotal, i.tax_amount) for i in items),
            discount_factor(sale.subtotal, sale.discount),
        )
        for code, (_, code_tax) in breakdown.items():
            assert code_tax == sum(
                (
                    ln.tax
                    for ln, i in zip(lines, items, strict=True)
                    if i.tax_code == code
                ),
                Decimal("0"),
            )
        for line in lines:
            assert line.discount >= 0
            assert line.taxable_base == line.taxable_base.quantize(Decimal("0.01"))

    def test_tax_drift_from_stored_precision_goes_to_the_largest_group(self):
        lines = [
            SaleLine(Decimal("10"), TaxCode.VAT_15, Decimal("10"), Decimal("1.5")),
            SaleLine(Decimal("10"), TaxCode.VAT_5, Decimal("10"), Decimal("0.5")),
        ]

        # La venta guardó 2.01 de IVA; recalculado daría 2.00
        result = invoice_lines(lines, Decimal("20"), Decimal("0"), Decimal("2.01"))

        assert [line.tax for line in result] == [Decimal("1.51"), Decimal("0.50")]
