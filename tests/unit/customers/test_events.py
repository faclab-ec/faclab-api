from unittest.mock import MagicMock

import pytest

from src.customers.app.commands.customer import (
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
)
from src.customers.domain.entities import Customer
from src.customers.domain.events import (
    CustomerActivated,
    CustomerCreated,
    CustomerDeactivated,
    CustomerUpdated,
)
from src.shared.domain.tax import TaxType
from src.shared.infra.events.event_bus import EventBus


@pytest.fixture(autouse=True)
def clear_event_bus():
    EventBus.clear()
    yield
    EventBus.clear()


def test_customer_created_event_to_dict():
    event = CustomerCreated(
        aggregate_id=1,
        customer_id=1,
        name="Test",
        tax_id="1710034065001",
    )
    d = event.to_dict()

    assert d["event_type"] == "CustomerCreated"
    assert d["aggregate_id"] == 1
    assert d["payload"]["customer_id"] == 1
    assert d["payload"]["name"] == "Test"
    assert d["payload"]["tax_id"] == "1710034065001"
    assert "event_id" in d
    assert "occurred_at" in d


def test_customer_updated_event_to_dict():
    event = CustomerUpdated(aggregate_id=1, customer_id=1, name="Updated")
    d = event.to_dict()

    assert d["event_type"] == "CustomerUpdated"
    assert d["payload"]["name"] == "Updated"


def test_customer_activated_event_to_dict():
    event = CustomerActivated(aggregate_id=1, customer_id=1)
    d = event.to_dict()

    assert d["event_type"] == "CustomerActivated"
    assert d["payload"]["customer_id"] == 1


def test_customer_deactivated_event_to_dict():
    event = CustomerDeactivated(aggregate_id=1, customer_id=1, reason="Inactive")
    d = event.to_dict()

    assert d["event_type"] == "CustomerDeactivated"
    assert d["payload"]["reason"] == "Inactive"


def test_create_handler_publishes_event():
    customer = Customer(
        id=1,
        name="Test",
        tax_id="1710034065001",
        tax_type=TaxType.RUC,
        is_active=True,
    )
    repo = MagicMock()
    repo.create.return_value = customer

    from src.shared.infra.events.event_bus_publisher import EventBusPublisher

    events_received = []
    EventBus.subscribe(CustomerCreated, lambda e: events_received.append(e))

    handler = CreateCustomerCommandHandler(repo, EventBusPublisher())
    handler.handle(
        CreateCustomerCommand(name="Test", tax_id="1710034065001", tax_type=1)
    )

    assert len(events_received) == 1
    assert events_received[0].customer_id == 1
    assert events_received[0].name == "Test"
