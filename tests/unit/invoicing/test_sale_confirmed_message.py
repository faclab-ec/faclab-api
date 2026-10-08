import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.invoicing.infra.event_handlers import build_sale_confirmed_message
from src.sales.domain.events import SaleConfirmed
from src.shared.domain.tax import TaxCode, TaxType
from src.shared.infra.kafka.producer import json_default


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
    }
    defaults.update(overrides)
    return SaleConfirmed(**defaults)


def _build(event: SaleConfirmed, customer: Customer | None = None) -> dict:
    customer_repo = MagicMock()
    customer_repo.get_by_id.return_value = customer
    product_repo = MagicMock()
    product_repo.get_by_ids.return_value = [
        Product(id=10, sku="SKU-10", name="Producto 10")
    ]
    return build_sale_confirmed_message(event, customer_repo, product_repo)


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
