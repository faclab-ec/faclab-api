from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.sales.app.commands import (
    RequestSaleInvoicingCommand,
    RequestSaleInvoicingCommandHandler,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem, SaleStatus
from src.sales.domain.events import SaleInvoicingRequested
from src.sales.domain.exceptions import (
    InsufficientPaymentError,
    InvalidSaleStatusError,
    SaleWithoutEmissionPointError,
)
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode


def _handler(
    sale: Sale | None, payments: list[Payment] | None = None
) -> tuple[RequestSaleInvoicingCommandHandler, MagicMock]:
    sale_repo = MagicMock()
    sale_repo.get_by_id.return_value = sale
    item_repo = MagicMock()
    item_repo.filter_by.return_value = [
        SaleItem(
            id=3,
            sale_id=1,
            product_id=10,
            quantity=2,
            unit_price=Decimal("10"),
            tax_code=TaxCode.VAT_15,
            tax_amount=Decimal("3"),
        )
    ]
    payment_repo = MagicMock()
    payment_repo.filter_by.return_value = (
        [
            Payment(
                id=7, sale_id=1, amount=Decimal("23"), payment_method=PaymentMethod.CASH
            )
        ]
        if payments is None
        else payments
    )
    publisher = MagicMock()
    handler = RequestSaleInvoicingCommandHandler(
        sale_repo, item_repo, payment_repo, publisher
    )
    return handler, publisher


def test_confirmed_sale_is_sent_again_without_touching_it():
    sale = Sale(
        id=1,
        customer_id=5,
        shift_id=2,
        branch_id=4,
        emission_point_id=6,
        number="V-001-000031",
        status=SaleStatus.CONFIRMED,
        subtotal=Decimal("20"),
        total=Decimal("23"),
    )
    handler, publisher = _handler(sale)

    result = handler.handle(RequestSaleInvoicingCommand(sale_id=1))

    assert result["status"] == SaleStatus.CONFIRMED
    [event] = publisher.publish.call_args.args
    assert isinstance(event, SaleInvoicingRequested)
    assert (event.sale_id, event.customer_id, event.source) == (1, 5, "pos")
    assert (event.branch_id, event.emission_point_id, event.number) == (
        4,
        6,
        "V-001-000031",
    )
    assert event.items == [
        {
            "product_id": 10,
            "quantity": 2,
            "unit_price": Decimal("10"),
            "discount": Decimal("0"),
            "tax_code": TaxCode.VAT_15,
            "tax_amount": Decimal("3"),
            "subtotal": Decimal("20"),
        }
    ]
    assert event.payments == [{"method": PaymentMethod.CASH, "amount": Decimal("23")}]


def _confirmed_sale() -> Sale:
    return Sale(
        id=1,
        shift_id=2,
        emission_point_id=6,
        status=SaleStatus.CONFIRMED,
        subtotal=Decimal("20"),
        total=Decimal("23"),
    )


def test_an_old_sale_sends_only_what_its_payments_applied():
    """Paid before S3.3 with cash in excess: `pagos` adds up to the total"""
    cash = Payment(
        id=7, sale_id=1, amount=Decimal("30"), payment_method=PaymentMethod.CASH
    )
    handler, publisher = _handler(_confirmed_sale(), [cash])

    handler.handle(RequestSaleInvoicingCommand(sale_id=1))

    [event] = publisher.publish.call_args.args
    assert event.payments == [{"method": PaymentMethod.CASH, "amount": Decimal("23")}]
    assert (cash.amount_tendered, cash.change) == (Decimal("30"), Decimal("7"))


def test_a_sale_its_payments_dont_cover_is_not_sent():
    """Confirmed before S3.3 without covering its total"""
    short = Payment(
        id=7, sale_id=1, amount=Decimal("20"), payment_method=PaymentMethod.TRANSFER
    )
    handler, publisher = _handler(_confirmed_sale(), [short])

    with pytest.raises(InsufficientPaymentError):
        handler.handle(RequestSaleInvoicingCommand(sale_id=1))
    publisher.publish.assert_not_called()


@pytest.mark.parametrize(
    "status", [SaleStatus.DRAFT, SaleStatus.INVOICED, SaleStatus.CANCELLED]
)
def test_only_confirmed_sales_can_be_sent_again(status):
    handler, publisher = _handler(Sale(id=1, status=status))

    with pytest.raises(InvalidSaleStatusError):
        handler.handle(RequestSaleInvoicingCommand(sale_id=1))
    publisher.publish.assert_not_called()


def test_missing_sale():
    handler, _ = _handler(None)

    with pytest.raises(NotFoundError):
        handler.handle(RequestSaleInvoicingCommand(sale_id=1))


def test_a_sale_without_emission_point_is_not_sent():
    """Sales from before S2.6 (and the old seed) have no emission point: the
    invoice would have no establishment nor sequential"""
    handler, publisher = _handler(Sale(id=1, status=SaleStatus.CONFIRMED))

    with pytest.raises(SaleWithoutEmissionPointError):
        handler.handle(RequestSaleInvoicingCommand(sale_id=1))
    publisher.publish.assert_not_called()
