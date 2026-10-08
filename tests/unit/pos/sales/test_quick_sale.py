from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.pos.sales.app.commands.quick_sale import (
    QuickSaleCommand,
    QuickSaleCommandHandler,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.sales.domain.entities import Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import InsufficientStockError
from src.shared.domain.exceptions import NotFoundError, ValidationError
from src.shared.domain.tax import TaxCode


def _make_shift(**overrides) -> Shift:
    defaults = {
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
    stock = MagicMock()
    stock.quantity = quantity
    return stock


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
    return repo


def _make_sale(**overrides) -> Sale:
    defaults = {
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
    defaults = {
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
        movement_repo=movement_repo or _mock_repo(),
        stock_repo=stock_repo or _mock_repo(),
        payment_repo=payment_repo or _mock_repo(),
        shift_repo=shift_repo or _mock_repo(),
        event_publisher=event_publisher or MagicMock(),
    )


def _quick_sale_command(**overrides):
    defaults = {
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
        payment_repo.create.assert_called_once()
        event_publisher.publish.assert_called_once()

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

        with pytest.raises(ValidationError):
            handler.handle(
                _quick_sale_command(
                    payments=[{"amount": 10.00, "payment_method": "CASH"}]
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
