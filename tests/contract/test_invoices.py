"""invoices v1: the examples in contracts/events/invoices/ match the schema that
faclab-invoicing validates its producer against, and core handles each of them."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from src.invoicing.infra import invoice_messages
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.sales.app.commands.invoice_sale import InvoiceSaleCommand
from tests.contract.contracts import errors, examples, validator

SCHEMA = validator("invoices")
EXAMPLES = examples("invoices")


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


def test_the_examples_cover_what_core_acts_on():
    assert {"invoice-authorized", "invoice-rejected"} <= set(EXAMPLES)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_match_the_contract(name):
    assert errors(SCHEMA, EXAMPLES[name]) == []


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_core_invoices_the_sale_only_when_authorized(command_handler, name):
    message = EXAMPLES[name]

    handle_invoice_message(message)

    if message["type"] == "InvoiceAuthorized":
        command_handler.handle.assert_called_once_with(
            InvoiceSaleCommand(
                sale_id=int(message["saleId"]), invoice_id=message["invoiceId"]
            )
        )
    else:
        command_handler.handle.assert_not_called()


def test_a_message_from_before_v1_is_handled_as_v1(command_handler):
    message = dict(EXAMPLES["invoice-authorized"])
    del message["schema_version"]

    handle_invoice_message(message)

    command_handler.handle.assert_called_once()
