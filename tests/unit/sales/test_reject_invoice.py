from unittest.mock import MagicMock

import pytest

from src.sales.app.commands import (
    RejectSaleInvoiceCommand,
    RejectSaleInvoiceCommandHandler,
)
from src.sales.domain.entities import InvoiceStatus, Sale, SaleStatus
from src.shared.domain.exceptions import NotFoundError


def _handler(sale: Sale | None) -> tuple[RejectSaleInvoiceCommandHandler, MagicMock]:
    sale_repo = MagicMock()
    sale_repo.get_by_id.return_value = sale
    return RejectSaleInvoiceCommandHandler(sale_repo), sale_repo


def _command() -> RejectSaleInvoiceCommand:
    return RejectSaleInvoiceCommand(sale_id=1, invoice_id="inv-1", reason="CLAVE")


def test_a_pending_invoice_becomes_rejected():
    sale = Sale(id=1, status=SaleStatus.CONFIRMED, invoice_status=InvoiceStatus.PENDING)
    handler, sale_repo = _handler(sale)

    result = handler.handle(_command())

    assert result["invoice_status"] == InvoiceStatus.REJECTED
    assert (result["invoice_id"], result["invoice_rejection_reason"]) == (
        "inv-1",
        "CLAVE",
    )
    sale_repo.update.assert_called_once_with(sale)


@pytest.mark.parametrize(
    ("status", "invoice_status"),
    [
        # Delivered again
        (SaleStatus.CONFIRMED, InvoiceStatus.REJECTED),
        (SaleStatus.INVOICED, InvoiceStatus.AUTHORIZED),
        # Sent before S3.3
        (SaleStatus.CONFIRMED, None),
        (SaleStatus.INVOICED, None),
        (SaleStatus.CANCELLED, None),
    ],
)
def test_anything_but_a_pending_invoice_is_left_as_is(status, invoice_status):
    sale = Sale(id=1, status=status, invoice_status=invoice_status)
    handler, sale_repo = _handler(sale)

    handler.handle(_command())

    assert sale.invoice_status == invoice_status
    sale_repo.update.assert_not_called()


def test_missing_sale():
    handler, _ = _handler(None)

    with pytest.raises(NotFoundError):
        handler.handle(_command())


def test_a_repeated_rejection_after_a_resend_is_ignored():
    """The sale was resent (PENDING again): the old invoice's rejection,
    delivered once more, doesn't mark the new one as rejected"""
    sale = Sale(
        id=1,
        status=SaleStatus.CONFIRMED,
        invoice_status=InvoiceStatus.PENDING,
        invoice_id="inv-1",
    )
    handler, sale_repo = _handler(sale)

    handler.handle(_command())

    assert sale.invoice_status == InvoiceStatus.PENDING
    sale_repo.update.assert_not_called()
