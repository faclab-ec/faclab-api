import json
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from src.catalog.product.domain.entities import Product
from src.sales.domain.events import SaleConfirmed
from src.shared.domain.tax import TaxCode
from src.shared.infra.kafka.event_handlers import _build_enriched_payload
from src.shared.infra.kafka.producer import _json_serializer


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


def _build(event: SaleConfirmed) -> dict:
    product = Product(id=10, sku="SKU-10", name="Producto 10")
    scope = MagicMock()
    scope.get.return_value.get_by_id.return_value = product
    with patch(
        "src.shared.infra.kafka.event_handlers.create_sync_scope"
    ) as create_scope:
        create_scope.return_value.__enter__.return_value = scope
        return _build_enriched_payload(event)


def test_item_carries_tax_code_instead_of_tax_rate():
    payload = _build(_make_event())

    item = payload["payload"]["items"][0]
    assert item["tax_code"] == TaxCode.VAT_15
    assert "tax_rate" not in item
    assert item["sku"] == "SKU-10"
    assert item["product_name"] == "Producto 10"


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

    raw = json.loads(json.dumps(_build(event), default=_json_serializer))

    item = raw["payload"]["items"][0]
    assert item["tax_code"] == "EXEMPT"
    assert item["tax_amount"] == "0"
