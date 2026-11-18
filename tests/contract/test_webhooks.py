"""The public contracts of the webhooks, v1 (S6.4): the snapshot in
`docs/public-api/webhooks/v1/` is what the code publishes, and the messages it
builds comply with it, closed (no field outside the contract)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.public_api.infra.schemas.sales import Sale
from src.webhooks.domain.types import TEST_EVENT, WebhookEventType
from src.webhooks.infra.contracts import event_schema, render, snapshot_path
from src.webhooks.infra.models import WebhookMessageModel
from src.webhooks.infra.schemas import (
    EVENT_MODELS,
    CreditNoteAuthorizedData,
    InvoiceAuthorizedData,
    InvoiceRejectedData,
    ProductUpdatedData,
    SaleCancelledData,
    StockChangedData,
    data_of,
)
from tests.contract.contracts import errors
from tests.sqlite import sqlite_session
from tests.webhooks_kit import WEBHOOK_MODELS, Kit

NOW = datetime(2026, 11, 18, 15, 4, 5, tzinfo=UTC)

SALE = {
    "id": 1204,
    "number": "V-001-000123",
    "channel": "api",
    "external_reference": "WEB-100234",
    "status": "CONFIRMED",
    "branch_id": 12,
    "emission_point_id": 31,
    "customer_id": None,
    "sale_date": NOW,
    "subtotal": Decimal("12.42"),
    "tax": Decimal("1.86"),
    "discount": Decimal("0"),
    "total": Decimal("14.28"),
    "payment_status": "PAID",
    "invoice_status": "PENDING",
    "invoice_id": None,
    "items": [
        {
            "id": 1,
            "product_id": 501,
            "presentation_id": 9,
            "presentation_name": "Unidad",
            "quantity": Decimal("3"),
            "unit_factor": Decimal("1"),
            "base_quantity": Decimal("3"),
            "unit_price": Decimal("4.14"),
            "discount": Decimal("0"),
            "tax_code": "VAT_15",
            "tax_amount": Decimal("1.863"),
            "subtotal": Decimal("12.42"),
        }
    ],
    "payments": [
        {"method": "TRANSFER", "amount": Decimal("14.28"), "reference": "pasarela-7f3a"}
    ],
    "created_at": NOW,
    "updated_at": NOW,
}

# The data of each type, built with the models the handlers use
DATA: dict[str, dict[str, Any]] = {
    WebhookEventType.SALE_CONFIRMED: data_of(Sale.model_validate(SALE)),
    WebhookEventType.SALE_CANCELLED: data_of(
        SaleCancelledData(
            sale_id=1204,
            number="V-001-000123",
            branch_id=12,
            channel="api",
            external_reference="WEB-100234",
            reason="Pedido anulado",
        )
    ),
    WebhookEventType.INVOICE_AUTHORIZED: data_of(
        InvoiceAuthorizedData(
            invoice_id="b56a64f1-de8f-5c84-af32-f7f233d03a0e",
            sale_id=1204,
            sale_number="V-001-000123",
            branch_id=12,
            external_reference=None,
        )
    ),
    WebhookEventType.INVOICE_REJECTED: data_of(
        InvoiceRejectedData(
            invoice_id="b56a64f1-de8f-5c84-af32-f7f233d03a0e",
            sale_id=1204,
            sale_number="V-001-000123",
            branch_id=12,
            reason="ERROR 45 : ERROR SECUENCIAL REGISTRADO",
        )
    ),
    WebhookEventType.CREDIT_NOTE_AUTHORIZED: data_of(
        CreditNoteAuthorizedData(
            credit_note_id=31,
            document_id="2f3a4b5c-6d7e-5f80-9a1b-2c3d4e5f6a7b",
            number="001-002-000000012",
            access_code="0" * 49,
            authorized_at=NOW,
            invoice_id="b56a64f1-de8f-5c84-af32-f7f233d03a0e",
            sale_id=1204,
            refund_id=45,
            branch_id=12,
        )
    ),
    WebhookEventType.STOCK_CHANGED: data_of(
        StockChangedData(
            product_id=501, sku="MART-1", branch_id=12, available=Decimal("13")
        )
    ),
    WebhookEventType.PRODUCT_UPDATED: data_of(
        ProductUpdatedData(
            product_id=501,
            sku="MART-1",
            action="updated",
            changed_fields=["salePrice"],
        )
    ),
}


def _closed(schema: Any) -> Any:
    """The contract without room for undocumented fields"""
    if isinstance(schema, dict):
        closed = {key: _closed(value) for key, value in schema.items()}
        if closed.get("type") == "object" and "properties" in closed:
            closed.setdefault("additionalProperties", False)
        return closed
    if isinstance(schema, list):
        return [_closed(value) for value in schema]
    return schema


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(WEBHOOK_MODELS)
    yield db
    db.close()


@pytest.mark.parametrize("event_type", list(EVENT_MODELS))
def test_the_snapshot_is_the_contract_of_the_code(event_type):
    assert snapshot_path(event_type).read_text() == render(event_schema(event_type)), (
        "a webhook's contract changed: run `make public-openapi` and review the "
        "diff (a field removed or changed needs version 2)"
    )
    Draft202012Validator.check_schema(event_schema(event_type))


def test_every_subscribable_type_and_the_test_event_have_a_contract():
    assert set(EVENT_MODELS) == {*WebhookEventType, TEST_EVENT}


@pytest.mark.parametrize("event_type", list(WebhookEventType))
def test_a_message_the_outbox_builds_complies_with_its_contract(session, event_type):
    kit = Kit(session)
    kit.create(event_types=[event_type])

    kit.outbox.enqueue(event_type, DATA[event_type], branch_id=12, occurred_at=NOW)

    message = session.scalars(select(WebhookMessageModel)).one()
    validator = Draft202012Validator(_closed(event_schema(event_type)))
    assert errors(validator, message.payload) == []


def test_the_test_event_complies_with_its_contract(session):
    kit = Kit(session)
    endpoint = kit.create()

    kit.send_test(endpoint["id"])

    message = session.scalars(select(WebhookMessageModel)).one()
    validator = Draft202012Validator(_closed(event_schema(TEST_EVENT)))
    assert errors(validator, message.payload) == []


def test_a_message_with_an_undocumented_field_does_not_comply(session):
    kit = Kit(session)
    kit.create(event_types=[WebhookEventType.STOCK_CHANGED])
    data = {**DATA[WebhookEventType.STOCK_CHANGED], "warehouseId": 101}

    kit.outbox.enqueue(WebhookEventType.STOCK_CHANGED, data, branch_id=12)

    message = session.scalars(select(WebhookMessageModel)).one()
    validator = Draft202012Validator(
        _closed(event_schema(WebhookEventType.STOCK_CHANGED))
    )
    assert errors(validator, message.payload)
