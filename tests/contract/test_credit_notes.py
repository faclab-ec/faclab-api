"""credit_notes.requested v1 and credit_notes.results v1: what core writes to the
outbox matches the contract, with its amounts adding up to what it credits, and core
applies each example of the results."""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.catalog.product.domain.entities import Product
from src.invoicing.app.commands.credit_notes import (
    ApplyCreditNoteResultCommand,
    ApplyCreditNoteResultCommandHandler,
)
from src.invoicing.domain.entities import CreditNote
from src.invoicing.domain.events import CreditNoteRequested
from src.invoicing.infra import credit_note_messages
from src.invoicing.infra.credit_note_messages import handle_credit_note_message
from src.invoicing.infra.event_handlers import (
    CREDIT_NOTES_REQUESTED_TOPIC,
    IssuingPoint,
    build_credit_note_message,
    credit_note_lines,
)
from src.pos.refund.domain.entities import Refund, RefundItem
from src.sales.domain.entities import SaleItem
from src.sales.domain.services import discount_factor
from src.shared.domain.tax import TaxCode
from src.shared.infra.database import Base
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.outbox.writer import OutboxWriter
from tests.contract.contracts import errors, examples, validator

SCHEMA = validator("credit_notes.requested")
EXAMPLES = examples("credit_notes.requested")
RESULTS_SCHEMA = validator("credit_notes.results")
RESULTS = examples("credit_notes.results")

POINT = IssuingPoint(
    tenant_id=UUID("6f1c2d3e-4b5a-4c7d-8e9f-0a1b2c3d4e5f"),
    issuer_ruc="1799999990001",
    establishment_code="002",
    establishment_address="Av. de la Prensa N58-12, Quito",
    emission_point_code="003",
)
PRODUCTS = [
    Product(id=10, sku="MART-16OZ", name="Martillo de uña 16 oz"),
    Product(id=11, sku="ABON-5KG", name="Abono orgánico 5 kg"),
]


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[OutboxMessageModel.__tablename__]]
    )
    with Session(engine) as session:
        yield session


def _refund_item(
    product_id: int, quantity: int, price: str, tax_code: TaxCode, **kw
) -> RefundItem:
    item = RefundItem(
        refund_id=45,
        original_sale_item_id=product_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=Decimal(price),
        tax_code=tax_code,
        **kw,
    )
    item.recalculate_tax()
    return item


def _refund_with_note(
    items: list[RefundItem],
    sale_subtotal: str = "100",
    sale_discount: str = "0",
) -> tuple[Refund, CreditNote]:
    refund = Refund(id=45, original_sale_id=1, number="D-002-000045", reason="Defecto")
    refund.recalculate_totals(
        items, discount_factor(Decimal(sale_subtotal), Decimal(sale_discount))
    )
    return refund, CreditNote(
        id=31,
        sale_id=1,
        refund_id=45,
        invoice_id="9a7f1c52-3b8e-5d41-a6f2-1c2d3e4f5a6b",
        reason="Defecto",
        subtotal=refund.subtotal,
        tax=refund.tax,
        total=refund.total,
    )


def _build(
    note: CreditNote,
    refund: Refund | None,
    items: list[Any],
    products: list[Product] | None = None,
    point: IssuingPoint = POINT,
) -> dict[str, Any]:
    product_repo = MagicMock()
    product_repo.get_by_ids.return_value = PRODUCTS if products is None else products
    return build_credit_note_message(
        CreditNoteRequested(
            aggregate_id=note.require_id(),
            credit_note_id=note.require_id(),
            sale_id=note.sale_id,
        ),
        note,
        refund,
        items,
        point,
        product_repo,
    )


def _written(session: Session, message: dict[str, Any]) -> dict[str, Any]:
    OutboxWriter(session).add(
        CREDIT_NOTES_REQUESTED_TOPIC,
        message,
        event_type="CreditNoteRequested",
        event_id=message["event_id"],
    )
    return session.scalars(select(OutboxMessageModel)).one().payload


TWO_RATES = [
    (10, 2, "8.500000", TaxCode.VAT_15, {"discount": Decimal("10.00")}),
    (11, 1, "6.000000", TaxCode.VAT_0, {}),
]


def _two_rates() -> list[RefundItem]:
    return [_refund_item(p, q, u, t, **kw) for p, q, u, t, kw in TWO_RATES]


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_match_the_contract(name):
    assert errors(SCHEMA, EXAMPLES[name]) == []


def test_the_examples_cover_a_refund_and_a_cancelled_sale():
    assert set(EXAMPLES) == {"refund", "cancelled-sale", "branch-without-address"}


def test_a_refund_written_to_the_outbox_matches_the_contract(session):
    items = _two_rates()
    refund, note = _refund_with_note(items, "100", "4")

    message = _written(session, _build(note, refund, items))

    assert errors(SCHEMA, message) == []
    assert message["schema_version"] == 1
    assert message["tenant_id"] == str(POINT.tenant_id)
    assert message["aggregate_id"] == 31
    payload = message["payload"]
    assert (payload["refund_id"], payload["refund_number"]) == (45, "D-002-000045")
    assert (payload["establishment_code"], payload["emission_point_code"]) == (
        "002",
        "003",
    )
    assert payload["reason"] == "Defecto"


def test_the_invoice_of_a_cancelled_sale_matches_the_contract(session):
    items = [
        SaleItem(
            sale_id=1,
            product_id=10,
            quantity=2,
            unit_price=Decimal("8.5"),
            tax_code=TaxCode.VAT_15,
        )
    ]
    items[0].recalculate_tax()
    note = CreditNote(
        id=32,
        sale_id=1,
        invoice_id="9a7f1c52-3b8e-5d41-a6f2-1c2d3e4f5a6b",
        reason="Venta anulada",
        subtotal=Decimal("17.00"),
        tax=Decimal("2.55"),
        total=Decimal("19.55"),
    )

    message = _written(session, _build(note, None, items))

    assert errors(SCHEMA, message) == []
    assert (message["payload"]["refund_id"], message["payload"]["refund_number"]) == (
        None,
        None,
    )


@pytest.mark.parametrize(
    "point_address",
    [None, "Av. de la Prensa N58-12, Quito"],
    ids=["without-address", "with-address"],
)
def test_a_branch_without_address_travels_as_null(session, point_address):
    items = _two_rates()
    refund, note = _refund_with_note(items)
    point = IssuingPoint(
        tenant_id=POINT.tenant_id,
        issuer_ruc=POINT.issuer_ruc,
        establishment_code="001",
        establishment_address=point_address,
        emission_point_code="001",
    )

    message = _written(session, _build(note, refund, items, point=point))

    assert errors(SCHEMA, message) == []
    assert message["payload"]["establishment_address"] == point_address


def test_products_gone_travel_as_null(session):
    items = _two_rates()
    refund, note = _refund_with_note(items)

    message = _written(session, _build(note, refund, items, products=[]))

    assert errors(SCHEMA, message) == []
    first = message["payload"]["items"][0]
    assert (first["sku"], first["product_name"]) == (None, None)


@pytest.mark.parametrize(
    ("items", "sale_subtotal", "sale_discount"),
    [
        (TWO_RATES, "100", "0"),
        (TWO_RATES, "100", "4"),
        (TWO_RATES, "33.33", "1.11"),
        ([(10, 3, "3.33", TaxCode.VAT_15, {})], "100", "7"),
        (
            [
                (10, 1, "3.33", TaxCode.VAT_15, {}),
                (11, 1, "1.10", TaxCode.VAT_5, {}),
                (10, 1, "2.00", TaxCode.VAT_0, {}),
            ],
            "19.97",
            "1.00",
        ),
    ],
    ids=["no-discount", "discount", "uneven", "one-line", "three-rates"],
)
def test_the_lines_add_up_to_what_it_credits(items, sale_subtotal, sale_discount):
    """valorModificacion comes from the lines: it has to be the refund's total"""
    built = [_refund_item(p, q, u, t, **kw) for p, q, u, t, kw in items]
    refund, note = _refund_with_note(built, sale_subtotal, sale_discount)

    lines = credit_note_lines(note, built)

    assert sum(line.taxable_base for line in lines) == refund.subtotal
    assert sum(line.tax for line in lines) == refund.tax
    assert sum(line.taxable_base + line.tax for line in lines) == refund.total, (
        "valorModificacion is not what the refund paid back"
    )


def test_a_field_without_documenting_breaks_the_contract():
    message = {
        **EXAMPLES["refund"],
        "payload": {**EXAMPLES["refund"]["payload"], "extra": 1},
    }

    assert errors(SCHEMA, message) != []


@pytest.mark.parametrize("field", ["reason", "invoice_id", "items", "total"])
def test_a_missing_field_breaks_the_contract(field):
    payload = dict(EXAMPLES["refund"]["payload"])
    del payload[field]

    assert errors(SCHEMA, {**EXAMPLES["refund"], "payload": payload}) != []


def test_an_empty_reason_breaks_the_contract():
    payload = {**EXAMPLES["refund"]["payload"], "reason": ""}

    assert errors(SCHEMA, {**EXAMPLES["refund"], "payload": payload}) != []


# --- credit_notes.results ---


@pytest.fixture
def command_handler(monkeypatch, in_tenant) -> MagicMock:
    handler = MagicMock()
    scope = MagicMock()
    scope.get.side_effect = lambda cls: (
        handler if cls is ApplyCreditNoteResultCommandHandler else MagicMock()
    )

    @contextmanager
    def fake_scope(tenant=None):
        yield scope

    monkeypatch.setattr(credit_note_messages, "create_sync_scope", fake_scope)
    return handler


@pytest.mark.parametrize("name", sorted(RESULTS))
def test_result_examples_match_the_contract(name):
    assert errors(RESULTS_SCHEMA, RESULTS[name]) == []


def test_an_authorized_result_needs_its_number():
    payload = {**RESULTS["credit-note-authorized"]["payload"], "number": None}
    message = {**RESULTS["credit-note-authorized"], "payload": payload}

    assert errors(RESULTS_SCHEMA, message) != []


@pytest.mark.parametrize("name", sorted(RESULTS))
def test_core_applies_each_result(command_handler, name):
    message = RESULTS[name]

    handle_credit_note_message(message)

    command = command_handler.handle.call_args.args[0]
    payload = message["payload"]
    assert isinstance(command, ApplyCreditNoteResultCommand)
    assert command.credit_note_id == payload["credit_note_id"]
    assert command.document_id == payload["document_id"]
    assert command.authorized is (message["event_type"] == "CreditNoteAuthorized")
    assert command.number == payload["number"]
    assert command.access_code == payload["access_code"]
    assert command.reason == payload["reason"]
    if payload["authorized_at"]:
        assert command.authorized_at is not None
        assert command.authorized_at.tzinfo is None
    else:
        assert command.authorized_at is None


def test_a_version_it_doesnt_know_is_dropped(command_handler):
    handle_credit_note_message(
        {**RESULTS["credit-note-authorized"], "schema_version": 2}
    )

    command_handler.handle.assert_not_called()


def test_a_message_without_a_credit_note_is_dropped(command_handler):
    handle_credit_note_message(
        {"event_type": "CreditNoteAuthorized", "schema_version": 1, "payload": {}}
    )

    command_handler.handle.assert_not_called()


def test_a_message_without_a_tenant_is_dropped(monkeypatch):
    scope = MagicMock(side_effect=AssertionError("no scope without a tenant"))
    monkeypatch.setattr(credit_note_messages, "create_sync_scope", scope)

    handle_credit_note_message(RESULTS["credit-note-authorized"])

    scope.assert_not_called()


def test_an_unknown_credit_note_is_given_up(command_handler):
    """Retrying won't bring it"""
    from src.shared.domain.exceptions import NotFoundError

    command_handler.handle.side_effect = NotFoundError("Credit note 31 not found")

    handle_credit_note_message(RESULTS["credit-note-authorized"])
