import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from config import config
from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.invoicing.domain.exceptions import InvoicingDisabledError
from src.invoicing.infra.event_handlers import (
    IssuingPoint,
    build_sale_confirmed_message,
    enqueue_invoicing_request,
    enqueue_sale_confirmed,
    issuing_point,
)
from src.organization.domain.entities import Branch, EmissionPoint
from src.sales.domain.events import SaleConfirmed, SaleInvoicingRequested
from src.sales.domain.exceptions import SaleWithoutEmissionPointError
from src.shared.domain.tax import TaxCode, TaxType
from src.shared.infra.kafka.producer import json_default
from src.tenancy.domain.entities import Tenant


def _make_event(**overrides) -> SaleConfirmed:
    defaults: dict[str, Any] = {
        "aggregate_id": 1,
        "sale_id": 1,
        "customer_id": 0,
        "items": [
            {
                "product_id": 10,
                "quantity": 2,
                "unit_price": Decimal("10.00"),
                "discount": Decimal("0"),
                "tax_code": TaxCode.VAT_15,
                "tax_amount": Decimal("3.00"),
                "subtotal": Decimal("20.00"),
            }
        ],
        "subtotal": Decimal("20.00"),
        "total": Decimal("23.00"),
        "source": "pos",
        "branch_id": 2,
        "emission_point_id": 5,
        "number": "V-001-000009",
    }
    defaults.update(overrides)
    return SaleConfirmed(**defaults)


POINT = IssuingPoint(
    tenant_id=UUID("00000000-0000-4000-8000-00000000000a"),
    issuer_ruc="1799999990001",
    establishment_code="001",
    establishment_address="Av. Amazonas N34-120, Quito",
    emission_point_code="002",
)


def _build(
    event: SaleConfirmed | SaleInvoicingRequested, customer: Customer | None = None
) -> dict:
    customer_repo = MagicMock()
    customer_repo.get_by_id.return_value = customer
    product_repo = MagicMock()
    product_repo.get_by_ids.return_value = [
        Product(id=10, sku="SKU-10", name="Producto 10")
    ]
    return build_sale_confirmed_message(event, POINT, customer_repo, product_repo)


def _repos(
    tenant: Tenant | None, branch: Branch | None, point: EmissionPoint | None
) -> tuple[MagicMock, MagicMock, MagicMock]:
    tenant_repo, branch_repo, point_repo = MagicMock(), MagicMock(), MagicMock()
    tenant_repo.get.return_value = tenant
    branch_repo.get_by_id.return_value = branch
    point_repo.get_by_id.return_value = point
    return tenant_repo, branch_repo, point_repo


def test_the_issuing_point_is_the_tenant_and_the_sale_emission_point(in_tenant):
    repos = _repos(
        Tenant(ruc="1799999990001", legal_name="Ferretería", id=in_tenant.tenant_id),
        Branch(id=2, establishment_code="003", name="Norte", address="Av. Norte"),
        EmissionPoint(id=5, branch_id=2, code="004"),
    )

    point = issuing_point(_make_event(), *repos)

    assert point == IssuingPoint(
        tenant_id=in_tenant.tenant_id,
        issuer_ruc="1799999990001",
        establishment_code="003",
        establishment_address="Av. Norte",
        emission_point_code="004",
    )
    # The branch is the emission point's
    repos[1].get_by_id.assert_called_once_with(2)


def test_a_sale_without_emission_point_cannot_be_invoiced(in_tenant):
    repos = _repos(
        Tenant(ruc="1799999990001", legal_name="Ferretería", id=in_tenant.tenant_id),
        None,
        None,
    )

    with pytest.raises(SaleWithoutEmissionPointError):
        issuing_point(_make_event(branch_id=None, emission_point_id=None), *repos)


def test_the_message_carries_the_tenant_issuer_and_emission_point():
    message = _build(_make_event())

    assert message["schema_version"] == 2
    assert message["tenant_id"] == str(POINT.tenant_id)
    payload = message["payload"]
    assert payload["sale_number"] == "V-001-000009"
    assert payload["issuer_ruc"] == "1799999990001"
    assert (payload["establishment_code"], payload["emission_point_code"]) == (
        "001",
        "002",
    )
    assert payload["establishment_address"] == "Av. Amazonas N34-120, Quito"


def test_item_carries_tax_code_and_product_data():
    message = _build(_make_event())

    item = message["payload"]["items"][0]
    assert item["tax_code"] == TaxCode.VAT_15
    assert "tax_rate" not in item
    assert item["sku"] == "SKU-10"
    assert item["product_name"] == "Producto 10"


def test_customer_is_embedded_when_the_sale_has_one():
    customer = Customer(
        id=7, name="Ana", tax_id="1710034065", tax_type=TaxType.NATIONAL_ID
    )

    message = _build(_make_event(customer_id=7), customer)

    assert message["payload"]["customer"]["tax_type"] == "NATIONAL_ID"
    assert message["event_type"] == "SaleConfirmed"


def test_tax_code_serializes_as_plain_string():
    """El consumidor de facturación valida tax_code contra el enum de códigos."""
    event = _make_event(
        items=[
            {
                "product_id": 10,
                "quantity": 1,
                "unit_price": Decimal("5.00"),
                "tax_code": TaxCode.EXEMPT,
                "tax_amount": Decimal("0"),
                "subtotal": Decimal("5.00"),
            }
        ]
    )

    raw = json.loads(json.dumps(_build(event), default=json_default))

    item = raw["payload"]["items"][0]
    assert item["tax_code"] == "EXEMPT"
    assert item["tax_amount"] == "0"


def test_items_carry_invoice_amounts_with_the_sale_discount_prorated():
    event = _make_event(
        items=[
            {
                "product_id": 10,
                "quantity": 2,
                "unit_price": Decimal("50.000000"),
                "discount": Decimal("10.00"),
                "tax_code": TaxCode.VAT_15,
                "tax_amount": Decimal("13.500000"),
                "subtotal": Decimal("90.000000"),
            },
            {
                "product_id": 10,
                "quantity": 1,
                "unit_price": Decimal("30.000000"),
                "discount": Decimal("0"),
                "tax_code": TaxCode.VAT_0,
                "tax_amount": Decimal("0"),
                "subtotal": Decimal("30.000000"),
            },
        ],
        subtotal=Decimal("120.00"),
        total_discount=Decimal("12.00"),
        total=Decimal("120.15"),
    )

    raw = json.loads(json.dumps(_build(event), default=json_default))

    first, second = raw["payload"]["items"]
    # Bruto 100: 10 de descuento de la línea + 9 del descuento global
    assert (first["invoice_discount"], first["invoice_base"], first["invoice_tax"]) == (
        "19.00",
        "81.00",
        "12.15",
    )
    assert (
        second["invoice_discount"],
        second["invoice_base"],
        second["invoice_tax"],
    ) == ("3.00", "27.00", "0.00")


def test_a_resend_is_the_same_message_with_its_own_event_id():
    original = _make_event()
    resend = SaleInvoicingRequested(
        aggregate_id=original.aggregate_id,
        sale_id=original.sale_id,
        customer_id=original.customer_id,
        items=original.items,
        subtotal=original.subtotal,
        total_discount=original.total_discount,
        total=original.total,
        payments=original.payments,
        source=original.source,
        branch_id=original.branch_id,
        emission_point_id=original.emission_point_id,
        number=original.number,
    )

    sent, resent = _build(original), _build(resend)

    assert resent["event_type"] == "SaleConfirmed"
    assert resent["event_id"] == resend.event_id != sent["event_id"]
    assert resent["payload"] == sent["payload"]


def test_a_resend_with_kafka_off_fails_instead_of_doing_nothing(monkeypatch):
    monkeypatch.setattr(config, "KAFKA_ENABLED", False)

    # A confirmed sale just skips Kafka; a resend asked by hand must say why not
    enqueue_sale_confirmed(_make_event())
    with pytest.raises(InvoicingDisabledError):
        enqueue_invoicing_request(SaleInvoicingRequested(aggregate_id=1, sale_id=1))
