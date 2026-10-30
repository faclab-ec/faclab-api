from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from src.invoicing.app.commands.discrepancies import (
    OpenInvoiceDiscrepancyCommand,
    OpenInvoiceDiscrepancyCommandHandler,
    ResolveInvoiceDiscrepancyCommand,
    ResolveInvoiceDiscrepancyCommandHandler,
)
from src.invoicing.infra import invoice_messages
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.sales.app.commands.invoice_sale import (
    InvoiceSaleCommand,
    InvoiceSaleCommandHandler,
)
from src.sales.app.commands.reject_invoice import (
    RejectSaleInvoiceCommand,
    RejectSaleInvoiceCommandHandler,
)
from src.sales.domain.entities import InvoiceStatus, SaleStatus
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError


@pytest.fixture
def scope_tenants(monkeypatch) -> list:
    """The `tenant` each scope was opened with"""
    return []


@pytest.fixture
def handlers(monkeypatch, scope_tenants) -> dict:
    """A mock per handler class the scope is asked for; the two sale commands
    share one, which answers the sale with its invoice authorized"""
    sale_handler = MagicMock()
    sale_handler.handle.return_value = {"invoice_status": InvoiceStatus.AUTHORIZED}
    found: dict = {
        InvoiceSaleCommandHandler: sale_handler,
        RejectSaleInvoiceCommandHandler: sale_handler,
    }
    scope = MagicMock()
    scope.get.side_effect = lambda cls: found.setdefault(cls, MagicMock())

    @contextmanager
    def fake_scope(tenant=None):
        scope_tenants.append(tenant)
        yield scope

    monkeypatch.setattr(invoice_messages, "create_sync_scope", fake_scope)
    return found


@pytest.fixture
def command_handler(handlers) -> MagicMock:
    return handlers[InvoiceSaleCommandHandler]


@pytest.fixture
def message_tenant(in_tenant):
    """The consumer set the message's tenant (its `faclab-tenant-id` header)"""
    return in_tenant


def _message(**overrides) -> dict:
    return {
        "type": "InvoiceAuthorized",
        "invoiceId": "inv-1",
        "saleId": "42",
        "status": "authorized",
        "occurredAt": "2026-10-08T15:00:00.000Z",
        **overrides,
    }


def test_authorized_invoice_invoices_the_sale(
    command_handler, message_tenant, scope_tenants
):
    handle_invoice_message(_message())

    command_handler.handle.assert_called_once_with(
        InvoiceSaleCommand(sale_id=42, invoice_id="inv-1")
    )
    # It runs in the message's tenant, already set
    assert scope_tenants == [None]


def test_a_message_without_a_tenant_is_dropped(command_handler, scope_tenants):
    """faclab-invoicing sends the faclab-tenant-id header since S2.8: without it
    the sale can't be looked up, and a retry wouldn't bring it"""
    handle_invoice_message(_message())

    assert scope_tenants == []
    command_handler.handle.assert_not_called()


def test_rejected_invoice_stops_being_pending(command_handler, message_tenant):
    handle_invoice_message(
        _message(
            type="InvoiceRejected",
            status="rejected",
            reason="ERROR SECUENCIAL REGISTRADO",
        )
    )

    command_handler.handle.assert_called_once_with(
        RejectSaleInvoiceCommand(
            sale_id=42, invoice_id="inv-1", reason="ERROR SECUENCIAL REGISTRADO"
        )
    )


@pytest.mark.parametrize("reason", [None, 7])
def test_a_rejection_without_a_readable_reason_still_applies(
    command_handler, message_tenant, reason
):
    """Messages from before S3.4 carry no reason"""
    message = _message(type="InvoiceRejected", status="rejected")
    if reason is not None:
        message["reason"] = reason

    handle_invoice_message(message)

    command_handler.handle.assert_called_once_with(
        RejectSaleInvoiceCommand(sale_id=42, invoice_id="inv-1", reason=None)
    )


@pytest.mark.parametrize(
    "event_type", ["InvoiceCreated", "InvoiceSigned", "InvoiceSent"]
)
def test_other_invoice_events_are_ignored(command_handler, message_tenant, event_type):
    handle_invoice_message(_message(type=event_type))

    command_handler.handle.assert_not_called()


def test_a_schema_version_core_does_not_know_is_skipped(
    command_handler, message_tenant
):
    handle_invoice_message(_message(schema_version=2))

    command_handler.handle.assert_not_called()


def test_message_without_a_numeric_sale_id_is_skipped(command_handler, message_tenant):
    handle_invoice_message(_message(saleId="not-a-number"))

    command_handler.handle.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        NotFoundError("Sale with id 42 not found"),
        InvalidSaleStatusError(SaleStatus.CANCELLED, "invoice"),
    ],
)
def test_errors_a_retry_cannot_fix_are_swallowed(
    command_handler, message_tenant, error
):
    command_handler.handle.side_effect = error

    handle_invoice_message(_message())


def test_unexpected_errors_propagate_so_the_message_is_retried(
    command_handler, message_tenant
):
    command_handler.handle.side_effect = ConnectionError("database is down")

    with pytest.raises(ConnectionError):
        handle_invoice_message(_message())


@pytest.mark.parametrize(
    ("message", "status"),
    [
        (_message(), InvoiceStatus.AUTHORIZED),
        (_message(type="InvoiceRejected", status="rejected"), InvoiceStatus.REJECTED),
    ],
)
def test_a_result_resolves_the_sales_reconciliation_discrepancy(
    handlers, command_handler, message_tenant, message, status
):
    command_handler.handle.return_value = {"invoice_status": status}

    handle_invoice_message(message)

    handlers[ResolveInvoiceDiscrepancyCommandHandler].handle.assert_called_once_with(
        ResolveInvoiceDiscrepancyCommand(sale_id=42)
    )


def test_a_repeated_rejection_after_a_resend_leaves_the_discrepancy(
    handlers, command_handler, message_tenant
):
    """The sale still waits for its new invoice"""
    command_handler.handle.return_value = {"invoice_status": InvoiceStatus.PENDING}

    handle_invoice_message(_message(type="InvoiceRejected", status="rejected"))

    assert ResolveInvoiceDiscrepancyCommandHandler not in handlers


def test_an_authorized_invoice_of_a_cancelled_sale_opens_a_discrepancy(
    handlers, command_handler, message_tenant, scope_tenants
):
    command_handler.handle.side_effect = InvalidSaleStatusError(
        SaleStatus.CANCELLED, "invoice"
    )

    handle_invoice_message(_message())

    handlers[OpenInvoiceDiscrepancyCommandHandler].handle.assert_called_once_with(
        OpenInvoiceDiscrepancyCommand(sale_id=42, invoice_id="inv-1")
    )
    # In a second scope of the message's tenant: the first one rolled back
    assert scope_tenants == [None, None]


def test_a_missing_sale_opens_no_discrepancy(handlers, command_handler, message_tenant):
    command_handler.handle.side_effect = NotFoundError("Sale with id 42 not found")

    handle_invoice_message(_message())

    assert OpenInvoiceDiscrepancyCommandHandler not in handlers
