from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.inventory.stock.domain.entities import Stock
from src.pos.sales.app.commands.quick_sale import (
    QuickSaleCommand,
    QuickSaleCommandHandler,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.stock import TerminalStock
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import (
    InsufficientPaymentError,
    InsufficientStockError,
    OverrideReasonRequiredError,
    PaymentExceedsBalanceError,
)
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.tax import TaxCode
from tests.unit.pos.terminals import AT_TERMINAL, numbering, terminal_resolver


def _make_shift(**overrides) -> Shift:
    defaults: dict[str, Any] = {
        "id": 1,
        "cashier_name": "Test Cashier",
        "status": ShiftStatus.OPEN,
        "opening_balance": Decimal("100"),
    }
    defaults.update(overrides)
    return Shift(**defaults)


def _make_product(**overrides):
    product = MagicMock()
    product.id = overrides.get("id", 1)
    product.sale_price = overrides.get("sale_price", Decimal("50.00"))
    product.tax_code = overrides.get("tax_code", TaxCode.VAT_12)
    return product


def _make_stock(quantity=100):
    return Stock(id=1, product_id=1, quantity=quantity)


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
        repo.first_for_update.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
    return repo


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": None,
        "is_final_consumer": True,
        "shift_id": 1,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 1,
        "quantity": 2,
        "unit_price": Decimal("50.00"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_12,
        "tax_amount": Decimal("12.00"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_payment(**overrides):
    payment = MagicMock()
    payment.sale_id = overrides.get("sale_id", 1)
    payment.amount = overrides.get("amount", Decimal("112.00"))
    payment.payment_method = overrides.get("payment_method", "CASH")
    payment.reference = overrides.get("reference")
    payment.dict.return_value = {
        "id": 1,
        "sale_id": payment.sale_id,
        "amount": payment.amount,
        "payment_method": payment.payment_method,
        "reference": payment.reference,
    }
    return payment


def _build_handler(
    sale_repo=None,
    sale_item_repo=None,
    product_repo=None,
    movement_repo=None,
    stock_repo=None,
    payment_repo=None,
    shift_repo=None,
    event_publisher=None,
):
    return QuickSaleCommandHandler(
        sale_repo=sale_repo or _mock_repo(),
        sale_item_repo=sale_item_repo or _mock_repo(),
        product_repo=product_repo or _mock_repo(),
        stock=TerminalStock(stock_repo or _mock_repo(), movement_repo or _mock_repo()),
        payment_repo=payment_repo or _mock_repo(),
        shift_repo=shift_repo or _mock_repo(),
        terminals=terminal_resolver(),
        numbering=numbering(),
        event_publisher=event_publisher or MagicMock(),
        session=MagicMock(),
    )


def _quick_sale_command(**overrides):
    defaults: dict[str, Any] = {
        "terminal": AT_TERMINAL,
        "items": [{"product_id": 1, "quantity": 2, "unit_price": 50.00}],
        "payments": [{"amount": 112.00, "payment_method": "CASH"}],
        "customer_id": None,
    }
    defaults.update(overrides)
    return QuickSaleCommand(**defaults)


class TestQuickSaleHappyPath:
    def test_quick_sale_final_consumer(self):
        """Venta rapida a consumidor final (sin customer_id)"""
        shift = _make_shift()
        product = _make_product()
        stock = _make_stock(quantity=100)
        sale = _make_sale()
        sale_item = _make_sale_item()
        payment = _make_payment()

        shift_repo = _mock_repo(entity=shift)
        sale_repo = _mock_repo(entity=sale)
        sale_item_repo = _mock_repo(entity=sale_item)
        product_repo = _mock_repo(entity=product)
        stock_repo = _mock_repo(entity=stock)
        payment_repo = _mock_repo(entity=payment)
        movement_repo = _mock_repo()
        event_publisher = MagicMock()

        handler = _build_handler(
            sale_repo=sale_repo,
            sale_item_repo=sale_item_repo,
            product_repo=product_repo,
            movement_repo=movement_repo,
            stock_repo=stock_repo,
            payment_repo=payment_repo,
            shift_repo=shift_repo,
            event_publisher=event_publisher,
        )

        result = handler.handle(_quick_sale_command())

        assert result["status"] == "CONFIRMED"
        assert result["is_final_consumer"] is True
        assert result["customer_id"] is None
        assert "items" in result
        assert "payments" in result
        sale_repo.create.assert_called_once()
        sale_item_repo.create.assert_called_once()
        movement_repo.create.assert_called_once()
        assert stock_repo.update.call_args[0][0].quantity == 98
        payment_repo.create.assert_called_once()
        event_publisher.publish.assert_called_once()

    def test_quick_sale_keeps_the_change_apart_from_what_is_applied(self):
        """Cash handed over in excess: the sale, the cash register and the
        invoice take the total, and the rest is the change"""
        payment_repo = _mock_repo()
        payment_repo.create.side_effect = lambda payment: payment
        event_publisher = MagicMock()
        handler = _build_handler(
            sale_repo=_mock_repo(entity=_make_sale()),
            sale_item_repo=_mock_repo(entity=_make_sale_item()),
            product_repo=_mock_repo(entity=_make_product()),
            stock_repo=_mock_repo(entity=_make_stock(quantity=100)),
            payment_repo=payment_repo,
            shift_repo=_mock_repo(entity=_make_shift()),
            event_publisher=event_publisher,
        )

        result = handler.handle(
            _quick_sale_command(
                payments=[
                    {"amount": 50.00, "payment_method": "DEBIT_CARD"},
                    {"amount": 70.00, "payment_method": "CASH"},
                ]
            )
        )

        card, cash = (call.args[0] for call in payment_repo.create.call_args_list)
        assert (card.amount, card.amount_tendered, card.change) == (
            Decimal("50.00"),
            Decimal("50.00"),
            Decimal("0"),
        )
        assert (cash.amount, cash.amount_tendered, cash.change) == (
            Decimal("62.00"),
            Decimal("70.00"),
            Decimal("8.00"),
        )
        assert result["payment_status"] == "PAID"
        event = event_publisher.publish.call_args.args[0]
        assert sum(p["amount"] for p in event.payments) == event.total

    def test_quick_sale_runs_at_the_terminal(self):
        """La venta queda en la sucursal, el punto de emisión y la terminal, toma el
        turno de la terminal, descuenta de su ubicación y recibe su número"""
        sale_repo = _mock_repo()
        sale_repo.create.side_effect = lambda sale: replace(sale, id=1)
        sale_repo.update.side_effect = lambda sale: sale
        # Read back after the event, as the real repository does
        sale_repo.get_by_id.side_effect = lambda _id: sale_repo.update.call_args.args[0]
        shift_repo = _mock_repo(entity=_make_shift())
        stock_repo = _mock_repo(entity=_make_stock(quantity=100))
        movement_repo = _mock_repo()

        handler = _build_handler(
            sale_repo=sale_repo,
            sale_item_repo=_mock_repo(entity=_make_sale_item()),
            product_repo=_mock_repo(entity=_make_product()),
            movement_repo=movement_repo,
            stock_repo=stock_repo,
            payment_repo=_mock_repo(entity=_make_payment()),
            shift_repo=shift_repo,
        )

        result = handler.handle(_quick_sale_command())

        shift_repo.first.assert_called_once_with(terminal_id=3, status="OPEN")
        created = sale_repo.create.call_args.args[0]
        assert (created.branch_id, created.emission_point_id, created.terminal_id) == (
            1,
            2,
            3,
        )
        stock_repo.first_for_update.assert_called_once_with(product_id=1, location_id=7)
        assert movement_repo.create.call_args.args[0].location_id == 7
        assert result["number"] == "V-001-000001"

    def test_quick_sale_with_customer(self):
        """Venta rapida con cliente registrado"""
        shift = _make_shift()
        product = _make_product()
        stock = _make_stock(quantity=100)
        sale = _make_sale(customer_id=10, is_final_consumer=False)
        sale_item = _make_sale_item()
        payment = _make_payment()

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            sale_item_repo=_mock_repo(entity=sale_item),
            product_repo=_mock_repo(entity=product),
            stock_repo=_mock_repo(entity=stock),
            payment_repo=_mock_repo(entity=payment),
            shift_repo=_mock_repo(entity=shift),
        )

        result = handler.handle(_quick_sale_command(customer_id=10))

        assert result["status"] == "CONFIRMED"

    def test_quick_sale_applies_sale_discount_before_tax(self):
        """El descuento global reduce la base del IVA y el total a cobrar"""
        sale_repo = _mock_repo()
        # Like the real repository: persist what the handler built and assign an id
        sale_repo.create.side_effect = lambda sale: replace(sale, id=1)
        sale_repo.get_by_id.side_effect = lambda _id: sale_repo.update.call_args.args[0]
        event_publisher = MagicMock()
        handler = _build_handler(
            sale_repo=sale_repo,
            sale_item_repo=_mock_repo(entity=_make_sale_item()),
            product_repo=_mock_repo(entity=_make_product()),
            stock_repo=_mock_repo(entity=_make_stock(quantity=100)),
            payment_repo=_mock_repo(entity=_make_payment(amount=Decimal("100.8"))),
            shift_repo=_mock_repo(entity=_make_shift()),
            event_publisher=event_publisher,
        )

        # subtotal 100 - 10% = 90 → IVA 12% = 10.8 → total 100.8; the front pays
        # with float arithmetic, so the amount is a hair below the exact total
        result = handler.handle(
            _quick_sale_command(
                discount_type="PERCENTAGE",
                discount_value=Decimal("10"),
                payments=[{"amount": 100.79999999999998, "payment_method": "CASH"}],
            )
        )

        assert result["discount_type"] == "PERCENTAGE"
        assert result["discount"] == Decimal("10")
        assert result["tax"] == Decimal("10.8")
        assert result["total"] == Decimal("100.8")
        assert result["payment_status"] == "PAID"
        assert sale_repo.create.call_args[0][0].discount_type == "PERCENTAGE"
        event = event_publisher.publish.call_args[0][0]
        assert event.total_discount == Decimal("10")
        assert event.total == Decimal("100.8")

    def test_quick_sale_rejects_invalid_discount_before_writing(self):
        sale_repo = _mock_repo(entity=_make_sale())
        handler = _build_handler(
            sale_repo=sale_repo, shift_repo=_mock_repo(entity=_make_shift())
        )

        with pytest.raises(ValidationError):
            handler.handle(
                _quick_sale_command(
                    discount_type="PERCENTAGE", discount_value=Decimal("150")
                )
            )
        sale_repo.create.assert_not_called()

    def test_quick_sale_uses_product_price_when_not_provided(self):
        """Usa el precio del producto cuando no se proporciona unit_price"""
        shift = _make_shift()
        product = _make_product(sale_price=Decimal("30.00"))
        stock = _make_stock(quantity=100)
        sale = _make_sale()
        # subtotal=60, tax_amount=7.20, total=67.20
        sale_item = _make_sale_item(
            unit_price=Decimal("30.00"), tax_amount=Decimal("7.20")
        )
        payment = _make_payment()

        product_repo = _mock_repo(entity=product)

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            sale_item_repo=_mock_repo(entity=sale_item),
            product_repo=product_repo,
            stock_repo=_mock_repo(entity=stock),
            payment_repo=_mock_repo(entity=payment),
            shift_repo=_mock_repo(entity=shift),
        )

        result = handler.handle(
            _quick_sale_command(
                items=[{"product_id": 1, "quantity": 2}],
                payments=[{"amount": 67.20, "payment_method": "CASH"}],
            )
        )

        assert result["status"] == "CONFIRMED"


class TestQuickSalePriceOverride:
    def _handle(self, item: dict):
        sale_item_repo = _mock_repo()
        sale_item_repo.create.side_effect = lambda sale_item: sale_item
        handler = _build_handler(
            sale_repo=_mock_repo(entity=_make_sale()),
            sale_item_repo=sale_item_repo,
            product_repo=_mock_repo(entity=_make_product(sale_price=Decimal("50"))),
            stock_repo=_mock_repo(entity=_make_stock()),
            payment_repo=_mock_repo(entity=_make_payment()),
            shift_repo=_mock_repo(entity=_make_shift()),
        )
        handler.handle(
            _quick_sale_command(
                items=[{"product_id": 1, "quantity": 1, **item}],
                payments=[{"amount": 100, "payment_method": "CASH"}],
            )
        )
        return sale_item_repo.create.call_args.args[0]

    def test_another_price_is_recorded_with_its_reason(self):
        sale_item = self._handle(
            {"unit_price": 45, "override_reason": "Cliente frecuente"}
        )

        assert sale_item.unit_price == Decimal("45")
        assert sale_item.price_override == Decimal("45")
        assert sale_item.override_reason == "Cliente frecuente"

    def test_list_price_is_not_an_override(self):
        sale_item = self._handle({"unit_price": 50.0})

        assert sale_item.price_override is None
        assert sale_item.override_reason is None

    def test_another_price_needs_a_reason(self):
        with pytest.raises(OverrideReasonRequiredError):
            self._handle({"unit_price": 45})


class TestQuickSaleErrors:
    def test_no_open_shift_raises_error(self):
        """Error cuando no hay turno abierto"""
        shift_repo = MagicMock()
        shift_repo.first.return_value = None

        handler = _build_handler(shift_repo=shift_repo)

        with pytest.raises(NoOpenShiftError):
            handler.handle(_quick_sale_command())

    def test_product_not_found_raises_error(self):
        """Error cuando un producto no existe"""
        shift = _make_shift()
        sale = _make_sale()

        product_repo = MagicMock()
        product_repo.get_by_id.return_value = None

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            product_repo=product_repo,
            shift_repo=_mock_repo(entity=shift),
        )

        with pytest.raises(NotFoundError):
            handler.handle(_quick_sale_command())

    def test_insufficient_stock_raises_error(self):
        """Error cuando no hay stock suficiente"""
        shift = _make_shift()
        product = _make_product()
        stock = _make_stock(quantity=1)
        sale = _make_sale()
        sale_item = _make_sale_item()

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            sale_item_repo=_mock_repo(entity=sale_item),
            product_repo=_mock_repo(entity=product),
            stock_repo=_mock_repo(entity=stock),
            shift_repo=_mock_repo(entity=shift),
        )

        with pytest.raises(InsufficientStockError):
            handler.handle(
                _quick_sale_command(
                    items=[{"product_id": 1, "quantity": 10, "unit_price": 50.00}]
                )
            )

    def test_insufficient_payment_raises_error(self):
        """Error cuando el pago no cubre el total"""
        shift = _make_shift()
        product = _make_product()
        stock = _make_stock(quantity=100)
        sale = _make_sale(
            subtotal=Decimal("100"), tax=Decimal("12"), total=Decimal("112")
        )
        sale_item = _make_sale_item()

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            sale_item_repo=_mock_repo(entity=sale_item),
            product_repo=_mock_repo(entity=product),
            stock_repo=_mock_repo(entity=stock),
            shift_repo=_mock_repo(entity=shift),
        )

        with pytest.raises(InsufficientPaymentError):
            handler.handle(
                _quick_sale_command(
                    payments=[{"amount": 10.00, "payment_method": "CASH"}]
                )
            )

    def test_payments_are_checked_before_locking_the_stock(self):
        stock_repo = _mock_repo(entity=_make_stock(quantity=100))
        handler = _build_handler(
            sale_repo=_mock_repo(entity=_make_sale()),
            sale_item_repo=_mock_repo(entity=_make_sale_item()),
            product_repo=_mock_repo(entity=_make_product()),
            stock_repo=stock_repo,
            shift_repo=_mock_repo(entity=_make_shift()),
        )

        with pytest.raises(InsufficientPaymentError):
            handler.handle(
                _quick_sale_command(
                    payments=[{"amount": 111.99, "payment_method": "CASH"}]
                )
            )

        stock_repo.first_for_update.assert_not_called()

    def test_only_cash_can_be_handed_over_in_excess(self):
        handler = _build_handler(
            sale_repo=_mock_repo(entity=_make_sale()),
            sale_item_repo=_mock_repo(entity=_make_sale_item()),
            product_repo=_mock_repo(entity=_make_product()),
            stock_repo=_mock_repo(entity=_make_stock(quantity=100)),
            shift_repo=_mock_repo(entity=_make_shift()),
        )

        with pytest.raises(PaymentExceedsBalanceError):
            handler.handle(
                _quick_sale_command(
                    payments=[{"amount": 120.00, "payment_method": "CREDIT_CARD"}]
                )
            )

    def test_invalid_payment_method_raises_error(self):
        """Error cuando el metodo de pago es invalido"""
        shift = _make_shift()
        product = _make_product()
        stock = _make_stock(quantity=100)
        sale = _make_sale()
        sale_item = _make_sale_item()

        handler = _build_handler(
            sale_repo=_mock_repo(entity=sale),
            sale_item_repo=_mock_repo(entity=sale_item),
            product_repo=_mock_repo(entity=product),
            stock_repo=_mock_repo(entity=stock),
            shift_repo=_mock_repo(entity=shift),
        )

        with pytest.raises(ValidationError):
            handler.handle(
                _quick_sale_command(
                    payments=[{"amount": 112.00, "payment_method": "BITCOIN"}]
                )
            )
