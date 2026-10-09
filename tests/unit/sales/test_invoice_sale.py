from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.sales.app.commands import InvoiceSaleCommand, InvoiceSaleCommandHandler
from src.sales.domain.entities import Sale, SaleStatus
from src.sales.domain.events import SaleInvoiced
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError


def _handler(
    sale: Sale | None,
) -> tuple[InvoiceSaleCommandHandler, MagicMock, MagicMock]:
    sale_repo = MagicMock()
    sale_repo.get_by_id.return_value = sale
    publisher = MagicMock()
    return InvoiceSaleCommandHandler(sale_repo, publisher), sale_repo, publisher


def _command() -> InvoiceSaleCommand:
    return InvoiceSaleCommand(sale_id=1, invoice_id="inv-1")


def test_confirmed_sale_becomes_invoiced():
    sale = Sale(id=1, customer_id=5, status=SaleStatus.CONFIRMED, total=Decimal("23"))
    handler, sale_repo, publisher = _handler(sale)

    result = handler.handle(_command())

    assert result["status"] == SaleStatus.INVOICED
    sale_repo.update.assert_called_once_with(sale)
    [event] = publisher.publish.call_args.args
    assert isinstance(event, SaleInvoiced)
    assert (event.sale_id, event.invoice_id, event.total) == (1, "inv-1", Decimal("23"))


def test_already_invoiced_sale_is_left_as_is():
    handler, sale_repo, publisher = _handler(Sale(id=1, status=SaleStatus.INVOICED))

    handler.handle(_command())

    sale_repo.update.assert_not_called()
    publisher.publish.assert_not_called()


def test_cancelled_sale_cannot_be_invoiced():
    handler, _, _ = _handler(Sale(id=1, status=SaleStatus.CANCELLED))

    with pytest.raises(InvalidSaleStatusError):
        handler.handle(_command())


def test_missing_sale():
    handler, _, _ = _handler(None)

    with pytest.raises(NotFoundError):
        handler.handle(_command())
