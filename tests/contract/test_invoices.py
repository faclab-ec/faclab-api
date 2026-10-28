"""invoices v1: the examples in contracts/events/invoices/ match the schema that
faclab-invoicing validates its producer against, and core handles each of them."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from src.invoicing.infra import invoice_messages
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.sales.app.commands.invoice_sale import InvoiceSaleCommand
from src.sales.app.commands.reject_invoice import RejectSaleInvoiceCommand
from tests.contract.contracts import errors, examples, validator

SCHEMA = validator("invoices")
EXAMPLES = examples("invoices")


@pytest.fixture
def command_handler(monkeypatch, in_tenant) -> MagicMock:
    """Runs in the message's tenant, as the consumer sets it from the header"""
    handler = MagicMock()
    scope = MagicMock()
    scope.get.return_value = handler

    @contextmanager
    def fake_scope(tenant=None):
        yield scope

    monkeypatch.setattr(invoice_messages, "create_sync_scope", fake_scope)
    return handler


def test_the_examples_cover_what_core_acts_on():
    assert {"invoice-authorized", "invoice-rejected"} <= set(EXAMPLES)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_match_the_contract(name):
    assert errors(SCHEMA, EXAMPLES[name]) == []


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_core_acts_only_on_the_sris_answer(command_handler, name):
    """Authorized: the sale is invoiced. Rejected: its invoice stops being
    pending (S3.3). Any other step is ignored"""
    message = EXAMPLES[name]

    handle_invoice_message(message)

    ids = {"sale_id": int(message["saleId"]), "invoice_id": message["invoiceId"]}
    if message["type"] == "InvoiceAuthorized":
        command_handler.handle.assert_called_once_with(InvoiceSaleCommand(**ids))
    elif message["type"] == "InvoiceRejected":
        # With the SRI's reason (S3.4), which the sale shows
        command_handler.handle.assert_called_once_with(
            RejectSaleInvoiceCommand(**ids, reason=message["reason"])
        )
    else:
        command_handler.handle.assert_not_called()


def test_the_reason_is_optional():
    """Messages from before S3.4 carry none"""
    message = dict(EXAMPLES["invoice-rejected"])
    del message["reason"]

    assert errors(SCHEMA, message) == []
    assert errors(SCHEMA, {**message, "reason": None}) == []
    assert errors(SCHEMA, {**message, "reason": 45}) != []


def test_a_message_from_before_v1_is_handled_as_v1(command_handler):
    message = dict(EXAMPLES["invoice-authorized"])
    del message["schema_version"]

    handle_invoice_message(message)

    command_handler.handle.assert_called_once()
