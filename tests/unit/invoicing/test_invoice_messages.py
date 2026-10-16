from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from src.invoicing.infra import invoice_messages
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.sales.app.commands.invoice_sale import InvoiceSaleCommand
from src.sales.domain.entities import SaleStatus
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource

SALE_TENANT = UUID("00000000-0000-4000-8000-0000000000b2")


@pytest.fixture
def scope_tenants(monkeypatch) -> list:
    """The `tenant` each scope was opened with"""
    return []


@pytest.fixture
def command_handler(monkeypatch, scope_tenants) -> MagicMock:
    handler = MagicMock()
    scope = MagicMock()
    scope.get.return_value = handler

    @contextmanager
    def fake_scope(tenant=None):
        scope_tenants.append(tenant)
        yield scope

    monkeypatch.setattr(invoice_messages, "create_sync_scope", fake_scope)
    return handler


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


def test_a_message_without_a_tenant_runs_in_its_sales(
    command_handler, scope_tenants, monkeypatch
):
    looked_up = []
    monkeypatch.setattr(
        invoice_messages,
        "_tenant_of_sale",
        lambda sale_id: looked_up.append(sale_id) or SALE_TENANT,
    )

    handle_invoice_message(_message())

    assert looked_up == [42]
    assert scope_tenants == [TenantContext(SALE_TENANT, TenantSource.MESSAGE)]
    command_handler.handle.assert_called_once_with(
        InvoiceSaleCommand(sale_id=42, invoice_id="inv-1")
    )


def test_a_message_without_a_tenant_for_an_unknown_sale_is_skipped(
    command_handler, monkeypatch
):
    monkeypatch.setattr(invoice_messages, "_tenant_of_sale", lambda sale_id: None)

    handle_invoice_message(_message())

    command_handler.handle.assert_not_called()


@pytest.mark.parametrize(
    "event_type", ["InvoiceCreated", "InvoiceSigned", "InvoiceSent", "InvoiceRejected"]
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
