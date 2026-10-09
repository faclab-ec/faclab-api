from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from src.invoicing.infra import invoice_messages
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.sales.app.commands.invoice_sale import InvoiceSaleCommand
from src.sales.domain.entities import SaleStatus
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError


@pytest.fixture
def command_handler(monkeypatch) -> MagicMock:
    handler = MagicMock()
    scope = MagicMock()
    scope.get.return_value = handler

    @contextmanager
    def fake_scope():
        yield scope

    monkeypatch.setattr(invoice_messages, "create_sync_scope", fake_scope)
    return handler


def _message(**overrides) -> dict:
    return {
        "type": "InvoiceAuthorized",
        "invoiceId": "inv-1",
        "saleId": "42",
        "status": "authorized",
        "occurredAt": "2026-10-08T15:00:00.000Z",
        **overrides,
    }


def test_authorized_invoice_invoices_the_sale(command_handler):
    handle_invoice_message(_message())

    command_handler.handle.assert_called_once_with(
        InvoiceSaleCommand(sale_id=42, invoice_id="inv-1")
    )


@pytest.mark.parametrize(
    "event_type", ["InvoiceCreated", "InvoiceSigned", "InvoiceSent", "InvoiceRejected"]
)
def test_other_invoice_events_are_ignored(command_handler, event_type):
    handle_invoice_message(_message(type=event_type))

    command_handler.handle.assert_not_called()


def test_message_without_a_numeric_sale_id_is_skipped(command_handler):
    handle_invoice_message(_message(saleId="not-a-number"))

    command_handler.handle.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        NotFoundError("Sale with id 42 not found"),
        InvalidSaleStatusError(SaleStatus.CANCELLED, "invoice"),
    ],
)
def test_errors_a_retry_cannot_fix_are_swallowed(command_handler, error):
    command_handler.handle.side_effect = error

    handle_invoice_message(_message())


def test_unexpected_errors_propagate_so_the_message_is_retried(command_handler):
    command_handler.handle.side_effect = ConnectionError("database is down")

    with pytest.raises(ConnectionError):
        handle_invoice_message(_message())
