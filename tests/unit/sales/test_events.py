from decimal import Decimal

import pytest

from src.sales.domain.events import (
    PaymentReceived,
    SaleCancelled,
    SaleConfirmed,
    SaleCreated,
    SaleInvoiced,
    SaleItemAdded,
    SaleItemRemoved,
)
from src.shared.infra.events.event_bus import EventBus


@pytest.fixture(autouse=True)
def clear_event_bus():
    EventBus.clear()
    yield
    EventBus.clear()


def test_sale_created_event_to_dict():
    """Test que SaleCreated se serializa correctamente"""
    event = SaleCreated(
        aggregate_id=1,
        sale_id=1,
        customer_id=10,
        total=Decimal("1500.50"),
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleCreated"
    assert event_dict["aggregate_id"] == 1
    assert event_dict["payload"]["sale_id"] == 1
    assert event_dict["payload"]["customer_id"] == 10
    assert event_dict["payload"]["total"] == 1500.50


def test_sale_confirmed_event_to_dict():
    """Test que SaleConfirmed se serializa correctamente"""
    items = [
        {"product_id": 1, "quantity": 10, "unit_price": 100.0},
        {"product_id": 2, "quantity": 5, "unit_price": 50.0},
    ]
    event = SaleConfirmed(
        aggregate_id=1,
        sale_id=1,
        customer_id=10,
        items=items,
        total=Decimal("1250.0"),
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleConfirmed"
    assert event_dict["payload"]["sale_id"] == 1
    assert event_dict["payload"]["items"] == items
    assert len(event_dict["payload"]["items"]) == 2


def test_sale_cancelled_event_to_dict():
    """Test que SaleCancelled se serializa correctamente"""
    items = [{"product_id": 1, "quantity": 10}]
    event = SaleCancelled(
        aggregate_id=1,
        sale_id=1,
        customer_id=10,
        items=items,
        reason="Customer request",
        was_confirmed=True,
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleCancelled"
    assert event_dict["payload"]["sale_id"] == 1
    assert event_dict["payload"]["reason"] == "Customer request"
    assert event_dict["payload"]["was_confirmed"] is True


def test_sale_invoiced_event_to_dict():
    """Test que SaleInvoiced se serializa correctamente"""
    event = SaleInvoiced(
        aggregate_id=1,
        sale_id=1,
        customer_id=10,
        invoice_number="INV-001",
        total=Decimal("1500.0"),
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleInvoiced"
    assert event_dict["payload"]["invoice_number"] == "INV-001"


def test_payment_received_event_to_dict():
    """Test que PaymentReceived se serializa correctamente"""
    event = PaymentReceived(
        aggregate_id=1,
        payment_id=1,
        sale_id=1,
        amount=Decimal("500.0"),
        payment_method="CASH",
        reference="REF-001",
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "PaymentReceived"
    assert event_dict["payload"]["payment_id"] == 1
    assert event_dict["payload"]["sale_id"] == 1
    assert event_dict["payload"]["amount"] == 500.0
    assert event_dict["payload"]["payment_method"] == "CASH"


def test_sale_item_added_event_to_dict():
    """Test que SaleItemAdded se serializa correctamente"""
    event = SaleItemAdded(
        aggregate_id=1,
        sale_id=1,
        sale_item_id=1,
        product_id=10,
        quantity=5,
        unit_price=Decimal("100.0"),
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleItemAdded"
    assert event_dict["payload"]["product_id"] == 10
    assert event_dict["payload"]["quantity"] == 5


def test_sale_item_removed_event_to_dict():
    """Test que SaleItemRemoved se serializa correctamente"""
    event = SaleItemRemoved(
        aggregate_id=1,
        sale_id=1,
        sale_item_id=1,
        product_id=10,
        quantity=5,
    )
    event_dict = event.to_dict()

    assert event_dict["event_type"] == "SaleItemRemoved"
    assert event_dict["payload"]["sale_item_id"] == 1


def test_event_bus_publishes_sale_created():
    """Test que el EventBus publica eventos correctamente"""
    published_events = []

    def handler(event):
        published_events.append(event)

    EventBus.subscribe(SaleCreated, handler)

    event = SaleCreated(
        aggregate_id=1, sale_id=1, customer_id=10, total=Decimal("1000.0")
    )
    EventBus.publish(event)

    assert len(published_events) == 1
    assert published_events[0].sale_id == 1
