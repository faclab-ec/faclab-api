"""sales.confirmed v2: what core really writes to the outbox matches
contracts/events/sales.confirmed/v2.schema.json, and so do the examples that
faclab-invoicing tests its consumer with. The v1 examples still match v1: the
consumer keeps accepting them during the transition."""

import copy
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.invoicing.infra.event_handlers import (
    SALES_CONFIRMED_TOPIC,
    IssuingPoint,
    build_sale_confirmed_message,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem
from src.sales.domain.events import (
    SaleConfirmed,
    SaleInvoicingRequested,
    sale_items_data,
    sale_payments_data,
)
from src.shared.domain.tax import TaxCode, TaxType
from src.shared.infra.database import Base
from src.shared.infra.outbox.models import OutboxMessageModel
from src.shared.infra.outbox.writer import OutboxWriter
from tests.contract.contracts import errors, examples, validator

# The outbox only writes inside a tenant context
pytestmark = pytest.mark.usefixtures("in_tenant")

SCHEMA = validator("sales.confirmed", 2)
EXAMPLES = examples("sales.confirmed", 2)
V1_SCHEMA = validator("sales.confirmed", 1)
V1_EXAMPLES = examples("sales.confirmed", 1)

POINT = IssuingPoint(
    tenant_id=UUID("00000000-0000-4000-8000-00000000000a"),
    issuer_ruc="1799999990001",
    establishment_code="002",
    establishment_address="Av. de la Prensa N58-12, Quito",
    emission_point_code="003",
)

CUSTOMER = Customer(
    id=7,
    name="Construcciones Andinas S.A.",
    tax_id="1790012345001",
    tax_type=TaxType.RUC,
    email="compras@andinas.ec",
    phone="022345678",
    address="Av. 10 de Agosto N24-56, Quito",
)
# Customers often have nothing but a name and a tax id
WITHOUT_CONTACT = Customer(
    id=8, name="María Quishpe", tax_id="1710034065", tax_type=TaxType.NATIONAL_ID
)
PRODUCTS = [
    Product(id=10, sku="MART-16OZ", name="Martillo de uña 16 oz"),
    Product(id=11, sku="ABON-5KG", name="Abono orgánico 5 kg"),
]


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[OutboxMessageModel.__tablename__]]
    )
    with Session(engine) as session:
        yield session


def _item(product_id: int, quantity: int, price: str, tax_code: TaxCode, **kw):
    item = SaleItem(
        sale_id=1,
        product_id=product_id,
        quantity=quantity,
        unit_price=Decimal(price),
        tax_code=tax_code,
        **kw,
    )
    item.recalculate_tax()
    return item


def _event(
    customer_id: int | None,
    event_type: type[SaleConfirmed | SaleInvoicingRequested] = SaleConfirmed,
    source: str = "pos",
    number: str | None = "V-002-000017",
) -> SaleConfirmed | SaleInvoicingRequested:
    """A sale with a line discount, a sale discount and two VAT rates."""
    items = [
        _item(10, 2, "8.500000", TaxCode.VAT_15, discount=Decimal("10.00")),
        _item(11, 1, "6.000000", TaxCode.VAT_0),
    ]
    sale = Sale(id=1, customer_id=customer_id)
    sale.apply_discount("AMOUNT", Decimal("1.00"))
    sale.recalculate_totals(items)
    payments = [
        Payment(sale_id=1, amount=Decimal("20.00"), payment_method=PaymentMethod.CASH),
        Payment(
            sale_id=1,
            amount=sale.total - Decimal("20.00"),
            payment_method=PaymentMethod.TRANSFER,
        ),
    ]
    return event_type(
        aggregate_id=1,
        sale_id=1,
        customer_id=customer_id,
        items=sale_items_data(items),
        subtotal=sale.subtotal,
        total_discount=sale.discount,
        total=sale.total,
        payments=sale_payments_data(payments),
        source=source,
        branch_id=2,
        emission_point_id=3,
        number=number,
    )


def _written(
    session: Session,
    event: SaleConfirmed | SaleInvoicingRequested,
    customer: Customer | None,
    products: list[Product],
    point: IssuingPoint = POINT,
) -> dict[str, Any]:
    """The message as the handler builds it and the outbox stores it."""
    customer_repo = MagicMock()
    customer_repo.get_by_id.return_value = customer
    product_repo = MagicMock()
    product_repo.get_by_ids.return_value = products
    OutboxWriter(session).add(
        SALES_CONFIRMED_TOPIC,
        build_sale_confirmed_message(event, point, customer_repo, product_repo),
        event_type="SaleConfirmed",
        event_id=event.event_id,
    )
    return session.scalars(select(OutboxMessageModel)).one().payload


@pytest.mark.parametrize(
    ("event", "customer", "products"),
    [
        (_event(7, source="admin"), CUSTOMER, PRODUCTS),
        (_event(8), WITHOUT_CONTACT, PRODUCTS),
        (_event(None), None, PRODUCTS),
        # The customer or the products were deleted after the sale
        (_event(9), None, PRODUCTS),
        (_event(7), CUSTOMER, []),
        (_event(7, SaleInvoicingRequested, source="admin"), CUSTOMER, PRODUCTS),
        # A sale confirmed before S2.6 has no number
        (_event(7, number=None), CUSTOMER, PRODUCTS),
    ],
    ids=[
        "full-customer",
        "customer-without-contact",
        "final-consumer",
        "customer-gone",
        "products-gone",
        "resend",
        "sale-without-number",
    ],
)
def test_written_messages_match_the_contract(session, event, customer, products):
    message = _written(session, event, customer, products)

    assert errors(SCHEMA, message) == []
    assert message["schema_version"] == 2


def test_the_message_says_who_issues_and_from_where(session):
    message = _written(session, _event(7), CUSTOMER, PRODUCTS)

    assert message["tenant_id"] == str(POINT.tenant_id)
    payload = message["payload"]
    assert {
        key: payload[key]
        for key in (
            "sale_number",
            "issuer_ruc",
            "establishment_code",
            "establishment_address",
            "emission_point_code",
        )
    } == {
        "sale_number": "V-002-000017",
        "issuer_ruc": "1799999990001",
        "establishment_code": "002",
        "establishment_address": "Av. de la Prensa N58-12, Quito",
        "emission_point_code": "003",
    }


def test_a_branch_without_address_travels_as_null(session):
    point = IssuingPoint(
        tenant_id=POINT.tenant_id,
        issuer_ruc=POINT.issuer_ruc,
        establishment_code="001",
        establishment_address=None,
        emission_point_code="001",
    )

    message = _written(session, _event(None), None, PRODUCTS, point)

    assert errors(SCHEMA, message) == []
    assert message["payload"]["establishment_address"] is None


def test_missing_contact_data_and_products_travel_as_null(session):
    message = _written(session, _event(8), WITHOUT_CONTACT, [])

    customer = message["payload"]["customer"]
    assert (customer["email"], customer["phone"], customer["address"]) == (
        None,
        None,
        None,
    )
    item = message["payload"]["items"][0]
    assert (item["sku"], item["product_name"]) == (None, None)


def test_the_edge_cases_have_examples():
    assert set(EXAMPLES) >= {
        "full-customer",
        "customer-without-contact",
        "final-consumer",
        "product-without-sku",
        "branch-without-address",
    }


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_match_the_contract(name):
    assert errors(SCHEMA, EXAMPLES[name]) == []


@pytest.mark.parametrize("name", sorted(V1_EXAMPLES))
def test_v1_examples_still_match_v1(name):
    assert errors(V1_SCHEMA, V1_EXAMPLES[name]) == []


def _set(path: str, value: Any) -> Callable[[dict], None]:
    *parents, key = path.split(".")

    def change(message: dict) -> None:
        for parent in parents:
            message = message[parent]
        message[key] = value

    return change


def _drop(path: str) -> Callable[[dict], None]:
    *parents, key = path.split(".")

    def change(message: dict) -> None:
        for parent in parents:
            message = message[parent]
        del message[key]

    return change


def _rename_customer(message: dict) -> None:
    message["payload"]["client"] = message["payload"].pop("customer")


@pytest.mark.parametrize(
    "change",
    [
        _drop("schema_version"),
        _set("schema_version", 1),
        _drop("tenant_id"),
        _set("tenant_id", "default"),
        _drop("payload.issuer_ruc"),
        _set("payload.establishment_code", "1"),
        _set("payload.emission_point_code", "000"),
        _drop("payload.establishment_address"),
        _rename_customer,
        _drop("payload.payments"),
        _set("payload.total", 26.79),
        _set("payload.customer.name", None),
        _set("payload.customer.tax_type", 2),
        _set("payload.source", "web"),
        _set("payload.undocumented", True),
    ],
    ids=[
        "no-version",
        "other-version",
        "no-tenant",
        "tenant-not-a-uuid",
        "no-issuer-ruc",
        "establishment-not-three-digits",
        "emission-point-000",
        "address-omitted",
        "renamed-field",
        "missing-field",
        "amount-as-number",
        "required-text-null",
        "enum-as-code",
        "unknown-source",
        "undocumented-field",
    ],
)
def test_incompatible_changes_break_the_contract(change):
    message = copy.deepcopy(EXAMPLES["full-customer"])

    change(message)

    assert errors(SCHEMA, message)
