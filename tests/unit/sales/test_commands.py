from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.catalog.product.domain.entities import Product
from src.sales.app.commands import (
    AddSaleItemCommand,
    AddSaleItemCommandHandler,
    CreateSaleCommand,
    CreateSaleCommandHandler,
    RegisterPaymentCommand,
    RegisterPaymentCommandHandler,
    RemoveSaleItemCommand,
    RemoveSaleItemCommandHandler,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem, SaleStatus
from src.sales.domain.exceptions import (
    InvalidSaleStatusError,
    PaymentExceedsBalanceError,
    SaleNotPayableError,
)
from src.shared.domain.exceptions import NotFoundError, ValidationError
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


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 10,
        "unit_price": Decimal("100.00"),
        "discount": Decimal("0"),
        "tax_code": TaxCode.VAT_12,
        "tax_amount": Decimal("120.00"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_product(**overrides) -> Product:
    defaults: dict[str, Any] = {
        "id": 100,
        "name": "Test Product",
        "sku": "TST-001",
        "tax_code": TaxCode.VAT_12,
    }
    defaults.update(overrides)
    return Product(**defaults)


def _make_payment(**overrides) -> Payment:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "amount": Decimal("500.00"),
        "payment_method": PaymentMethod.CASH,
    }
    defaults.update(overrides)
    return Payment(**defaults)


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
        repo.get_all.return_value = entities
    return repo


def test_create_sale_command_handler():
    """Test crear una venta"""
    sale = _make_sale()
    repo = _mock_repo(entity=sale)
    event_publisher = MagicMock()
    handler = CreateSaleCommandHandler(repo, event_publisher)

    command = CreateSaleCommand(customer_id=10, notes="Test sale")
    result = handler.handle(command)

    repo.create.assert_called_once()
    assert result["customer_id"] == 10
    assert result["status"] == "DRAFT"


def test_create_sale_publishes_event():
    """Test que crear una venta publica evento"""
    from src.sales.domain.events import SaleCreated

    sale = _make_sale()
    repo = _mock_repo(entity=sale)
    event_publisher = MagicMock()
    handler = CreateSaleCommandHandler(repo, event_publisher)

    handler.handle(CreateSaleCommand(customer_id=10))

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, SaleCreated)
    assert published_event.sale_id == 1
    assert published_event.customer_id == 10


def test_add_sale_item_command_handler():
    """Test agregar un item a una venta"""
    sale = _make_sale()
    sale_item = _make_sale_item()
    product = _make_product()
    sale_repo = _mock_repo(entity=sale)
    item_repo = _mock_repo(entity=sale_item, entities=[sale_item])
    product_repo = _mock_repo(entity=product)
    event_publisher = MagicMock()
    handler = AddSaleItemCommandHandler(
        sale_repo, item_repo, product_repo, event_publisher
    )

    command = AddSaleItemCommand(
        sale_id=1,
        product_id=100,
        quantity=10,
        unit_price=Decimal("100.0"),
        discount=Decimal("0.0"),
    )
    result = handler.handle(command)

    item_repo.create.assert_called_once()
    sale_repo.update.assert_called_once()
    assert result["product_id"] == 100
    assert result["quantity"] == 10


def test_add_sale_item_only_draft():
    """Test que solo se pueden agregar items a ventas en DRAFT"""
    sale = _make_sale(status=SaleStatus.CONFIRMED)
    sale_item = _make_sale_item()
    product = _make_product()
    sale_repo = _mock_repo(entity=sale)
    item_repo = _mock_repo(entity=sale_item)
    product_repo = _mock_repo(entity=product)
    handler = AddSaleItemCommandHandler(sale_repo, item_repo, product_repo, MagicMock())

    command = AddSaleItemCommand(
        sale_id=1, product_id=100, quantity=10, unit_price=Decimal("100.0")
    )

    with pytest.raises(InvalidSaleStatusError):
        handler.handle(command)


def test_add_sale_item_sale_not_found():
    """Test que falla si la venta no existe"""
    sale_repo = _mock_repo()
    sale_repo.get_by_id.return_value = None
    item_repo = _mock_repo()
    product_repo = _mock_repo()
    handler = AddSaleItemCommandHandler(sale_repo, item_repo, product_repo, MagicMock())

    command = AddSaleItemCommand(
        sale_id=999, product_id=100, quantity=10, unit_price=Decimal("100.0")
    )

    with pytest.raises(NotFoundError):
        handler.handle(command)


def test_remove_sale_item_command_handler():
    """Test eliminar un item de una venta"""
    sale = _make_sale()
    sale_item = _make_sale_item()
    sale_repo = _mock_repo(entity=sale)
    item_repo = _mock_repo(entity=sale_item, entities=[])
    handler = RemoveSaleItemCommandHandler(sale_repo, item_repo, MagicMock())

    command = RemoveSaleItemCommand(sale_id=1, sale_item_id=1)
    result = handler.handle(command)

    item_repo.delete.assert_called_once()
    sale_repo.update.assert_called_once()
    assert result["success"] is True


def test_register_payment_command_handler():
    """Test registrar un pago"""
    sale = _make_sale(total=Decimal("1000.00"))
    payment = _make_payment()
    sale_repo = _mock_repo(entity=sale)
    payment_repo = _mock_repo(entity=payment, entities=[payment])
    handler = RegisterPaymentCommandHandler(sale_repo, payment_repo, MagicMock())

    command = RegisterPaymentCommand(
        sale_id=1,
        amount=Decimal("500.0"),
        payment_method="CASH",
        reference="REF-001",
    )
    result = handler.handle(command)

    payment_repo.create.assert_called_once()
    sale_repo.update.assert_called_once()
    assert result["amount"] == Decimal("500.00")


def test_register_payment_invalid_method():
    """Test que falla con método de pago inválido"""
    sale = _make_sale()
    sale_repo = _mock_repo(entity=sale)
    payment_repo = _mock_repo()
    handler = RegisterPaymentCommandHandler(sale_repo, payment_repo, MagicMock())

    command = RegisterPaymentCommand(
        sale_id=1,
        amount=Decimal("500.0"),
        payment_method="BITCOIN",  # Método inválido
    )

    with pytest.raises(ValidationError, match="Invalid payment method"):
        handler.handle(command)


def test_register_payment_sale_not_found():
    """Test que falla si la venta no existe"""
    sale_repo = _mock_repo()
    sale_repo.get_by_id.return_value = None
    payment_repo = _mock_repo()
    handler = RegisterPaymentCommandHandler(sale_repo, payment_repo, MagicMock())

    command = RegisterPaymentCommand(
        sale_id=999, amount=Decimal("500.0"), payment_method="CASH"
    )

    with pytest.raises(NotFoundError):
        handler.handle(command)


@pytest.mark.parametrize("status", [SaleStatus.CANCELLED, SaleStatus.INVOICED])
def test_register_payment_rejects_cancelled_or_invoiced_sales(status):
    sale_repo = _mock_repo(entity=_make_sale(status=status, total=Decimal("100")))
    payment_repo = _mock_repo(entities=[])
    handler = RegisterPaymentCommandHandler(sale_repo, payment_repo, MagicMock())

    with pytest.raises(SaleNotPayableError):
        handler.handle(
            RegisterPaymentCommand(
                sale_id=1, amount=Decimal("10"), payment_method="CASH"
            )
        )
    payment_repo.create.assert_not_called()
    sale_repo.update.assert_not_called()


def test_register_payment_keeps_the_change_of_cash_in_excess():
    sale = _make_sale(total=Decimal("100"))
    payment_repo = _mock_repo(entities=[_make_payment(amount=Decimal("60"))])
    # Persisted with its id
    payment_repo.create.side_effect = lambda payment: replace(payment, id=2)
    handler = RegisterPaymentCommandHandler(
        _mock_repo(entity=sale), payment_repo, MagicMock()
    )

    result = handler.handle(
        RegisterPaymentCommand(sale_id=1, amount=Decimal("50"), payment_method="CASH")
    )

    assert (result["amount"], result["amount_tendered"], result["change"]) == (
        Decimal("40"),
        Decimal("50"),
        Decimal("10"),
    )
    assert sale.payment_status == "PAID"


def test_register_payment_rejects_a_card_payment_above_the_balance():
    payment_repo = _mock_repo(entities=[])
    handler = RegisterPaymentCommandHandler(
        _mock_repo(entity=_make_sale(total=Decimal("100"))), payment_repo, MagicMock()
    )

    with pytest.raises(PaymentExceedsBalanceError):
        handler.handle(
            RegisterPaymentCommand(
                sale_id=1, amount=Decimal("101"), payment_method="CREDIT_CARD"
            )
        )
    payment_repo.create.assert_not_called()
