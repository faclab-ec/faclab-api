from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.pos.sales.app.queries.generate_receipt import (
    GenerateReceiptQuery,
    GenerateReceiptQueryHandler,
)
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode


def _make_sale_model(**overrides):
    sale = MagicMock()
    sale.id = overrides.get("id", 1)
    sale.sale_date = overrides.get("sale_date", datetime(2026, 3, 14, 10, 30))
    sale.status = overrides.get("status", "CONFIRMED")
    sale.customer_id = overrides.get("customer_id")
    sale.shift_id = overrides.get("shift_id")
    sale.is_final_consumer = overrides.get("is_final_consumer", True)
    sale.subtotal = overrides.get("subtotal", Decimal("100"))
    sale.tax = overrides.get("tax", Decimal("12"))
    sale.discount = overrides.get("discount", Decimal("0"))
    sale.discount_type = overrides.get("discount_type")
    sale.discount_value = overrides.get("discount_value", Decimal("0"))
    sale.total = overrides.get("total", Decimal("112"))
    return sale


def _make_item_model(**overrides):
    item = MagicMock()
    item.unit_price = overrides.get("unit_price", Decimal("100"))
    item.quantity = overrides.get("quantity", 1)
    item.discount = overrides.get("discount", Decimal("0"))
    item.tax_code = overrides.get("tax_code", TaxCode.VAT_12)
    item.tax_amount = overrides.get("tax_amount", Decimal("12"))
    item.price_override = overrides.get("price_override")
    item.override_reason = overrides.get("override_reason")
    return item


def _make_payment_model(**overrides):
    payment = MagicMock()
    payment.payment_method = overrides.get("payment_method", "CASH")
    payment.amount = overrides.get("amount", Decimal("112"))
    payment.reference = overrides.get("reference")
    return payment


def _make_customer_model(**overrides):
    customer = MagicMock()
    customer.name = overrides.get("name", "Juan Perez")
    customer.tax_id = overrides.get("tax_id", "1234567890001")
    customer.address = overrides.get("address", "Quito, Ecuador")
    return customer


def _make_shift_model(**overrides):
    shift = MagicMock()
    shift.cashier_name = overrides.get("cashier_name", "Maria Lopez")
    return shift


def _build_handler():
    handler = GenerateReceiptQueryHandler.__new__(GenerateReceiptQueryHandler)
    handler.session = MagicMock()
    return handler


class TestGenerateReceiptQueryHandler:
    def test_receipt_happy_path(self):
        handler = _build_handler()
        sale = _make_sale_model(customer_id=10, shift_id=1, is_final_consumer=False)
        item = _make_item_model()
        payment = _make_payment_model()
        customer = _make_customer_model()
        shift = _make_shift_model()

        # Setup query chain mocks
        query_mock = handler.session.query

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [payment]
            elif model_name == "CustomerModel":
                mock.filter.return_value.first.return_value = customer
            elif model_name == "ShiftModel":
                mock.filter.return_value.first.return_value = shift
            else:
                # SaleItemModel + ProductModel.name join
                mock.join.return_value.filter.return_value.all.return_value = [
                    (item, "Product A")
                ]
            return mock

        query_mock.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        assert result["sale_id"] == 1
        assert result["status"] == "CONFIRMED"
        assert result["cashier"] == "Maria Lopez"
        assert result["customer"]["name"] == "Juan Perez"
        assert result["customer"]["tax_id"] == "1234567890001"
        assert result["is_final_consumer"] is False
        assert len(result["items"]) == 1
        assert result["items"][0]["product_name"] == "Product A"
        assert result["subtotal"] == Decimal("100")
        assert result["tax"] == Decimal("12")
        assert result["total"] == Decimal("112")
        assert len(result["payments"]) == 1
        assert result["payments"][0]["method"] == "CASH"
        assert result["total_paid"] == Decimal("112")
        assert result["change"] == Decimal("0")

    def test_receipt_final_consumer(self):
        handler = _build_handler()
        sale = _make_sale_model(is_final_consumer=True)
        item = _make_item_model()
        payment = _make_payment_model()

        query_mock = handler.session.query

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [payment]
            else:
                mock.join.return_value.filter.return_value.all.return_value = [
                    (item, "Product A")
                ]
            return mock

        query_mock.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        assert result["is_final_consumer"] is True
        assert result["customer"] is None

    def test_receipt_tax_breakdown_mixed_rates(self):
        handler = _build_handler()
        sale = _make_sale_model(
            subtotal=Decimal("200"),
            tax=Decimal("12"),
            total=Decimal("212"),
        )
        item_12 = _make_item_model(
            unit_price=Decimal("100"),
            tax_code=TaxCode.VAT_12,
            tax_amount=Decimal("12"),
        )
        item_0 = _make_item_model(
            unit_price=Decimal("100"), tax_code=TaxCode.VAT_0, tax_amount=Decimal("0")
        )
        payment = _make_payment_model(amount=Decimal("212"))

        query_mock = handler.session.query

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [payment]
            else:
                mock.join.return_value.filter.return_value.all.return_value = [
                    (item_0, "Product Zero"),
                    (item_12, "Product IVA"),
                ]
            return mock

        query_mock.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        assert len(result["tax_breakdown"]) == 2
        breakdown_0 = next(
            t for t in result["tax_breakdown"] if t["tax_rate"] == Decimal("0")
        )
        breakdown_12 = next(
            t for t in result["tax_breakdown"] if t["tax_rate"] == Decimal("12")
        )
        assert breakdown_0["taxable_base"] == Decimal("100")
        assert breakdown_0["tax_amount"] == Decimal("0")
        assert breakdown_12["taxable_base"] == Decimal("100")
        assert breakdown_12["tax_amount"] == Decimal("12")

    def test_receipt_tax_breakdown_prorates_sale_discount(self):
        """Un descuento global de 50 sobre 200 reduce cada base al 75%"""
        handler = _build_handler()
        sale = _make_sale_model(
            subtotal=Decimal("200"),
            discount=Decimal("50"),
            discount_type="AMOUNT",
            discount_value=Decimal("50"),
            tax=Decimal("9"),
            total=Decimal("159"),
        )
        item_12 = _make_item_model(tax_code=TaxCode.VAT_12, tax_amount=Decimal("12"))
        item_0 = _make_item_model(tax_code=TaxCode.VAT_0, tax_amount=Decimal("0"))

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [
                    _make_payment_model(amount=Decimal("159"))
                ]
            else:
                mock.join.return_value.filter.return_value.all.return_value = [
                    (item_0, "Product Zero"),
                    (item_12, "Product IVA"),
                ]
            return mock

        handler.session.query.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        breakdown = {t["tax_code"]: t for t in result["tax_breakdown"]}
        assert breakdown[TaxCode.VAT_0]["taxable_base"] == Decimal("75")
        assert breakdown[TaxCode.VAT_12]["taxable_base"] == Decimal("75")
        assert breakdown[TaxCode.VAT_12]["tax_amount"] == Decimal("9")
        assert sum(t["tax_amount"] for t in result["tax_breakdown"]) == result["tax"]

    def test_receipt_tax_breakdown_sorted_by_rate(self):
        """El desglose se ordena por tarifa (no alfabético) y luego por código."""
        handler = _build_handler()
        sale = _make_sale_model()
        items = [
            (_make_item_model(tax_code=TaxCode.VAT_15), "P15"),
            (_make_item_model(tax_code=TaxCode.VAT_5), "P5"),
            (_make_item_model(tax_code=TaxCode.VAT_0), "P0"),
            (_make_item_model(tax_code=TaxCode.EXEMPT), "PEX"),
        ]
        payment = _make_payment_model()

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [payment]
            else:
                mock.join.return_value.filter.return_value.all.return_value = items
            return mock

        handler.session.query.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        assert [t["tax_code"] for t in result["tax_breakdown"]] == [
            TaxCode.EXEMPT,
            TaxCode.VAT_0,
            TaxCode.VAT_5,
            TaxCode.VAT_15,
        ]
        assert [t["tax_rate"] for t in result["tax_breakdown"]] == [
            Decimal("0"),
            Decimal("0"),
            Decimal("5"),
            Decimal("15"),
        ]

    def test_receipt_change_calculation(self):
        handler = _build_handler()
        sale = _make_sale_model(total=Decimal("100"))
        item = _make_item_model()
        payment = _make_payment_model(amount=Decimal("120"))

        query_mock = handler.session.query

        def query_side_effect(model, *args):
            mock = MagicMock()
            model_name = getattr(model, "__name__", str(model))

            if model_name == "SaleModel":
                mock.filter.return_value.first.return_value = sale
            elif model_name == "PaymentModel":
                mock.filter.return_value.all.return_value = [payment]
            else:
                mock.join.return_value.filter.return_value.all.return_value = [
                    (item, "Product A")
                ]
            return mock

        query_mock.side_effect = query_side_effect

        result = handler._handle(GenerateReceiptQuery(sale_id=1))

        assert result["total_paid"] == Decimal("120")
        assert result["change"] == Decimal("20")

    def test_receipt_sale_not_found(self):
        handler = _build_handler()

        query_mock = handler.session.query
        mock = MagicMock()
        mock.filter.return_value.first.return_value = None
        query_mock.return_value = mock

        with pytest.raises(NotFoundError):
            handler._handle(GenerateReceiptQuery(sale_id=999))
