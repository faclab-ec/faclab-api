import pytest

from src.shared.infra.events.event_bus import EventBus
from src.suppliers.domain.events import (
    SupplierActivated,
    SupplierCreated,
    SupplierDeactivated,
)


@pytest.fixture(autouse=True)
def clear_event_bus():
    EventBus.clear()
    yield
    EventBus.clear()


def test_supplier_created_event_to_dict():
    event = SupplierCreated(
        aggregate_id=1,
        supplier_id=1,
        name="ACME Corp",
        tax_id="1710034065001",
    )
    d = event.to_dict()

    assert d["event_type"] == "SupplierCreated"
    assert d["aggregate_id"] == 1
    assert d["payload"]["supplier_id"] == 1
    assert d["payload"]["name"] == "ACME Corp"
    assert d["payload"]["tax_id"] == "1710034065001"
    assert "event_id" in d
    assert "occurred_at" in d


def test_supplier_activated_event_to_dict():
    event = SupplierActivated(aggregate_id=1, supplier_id=1)
    d = event.to_dict()

    assert d["event_type"] == "SupplierActivated"
    assert d["payload"]["supplier_id"] == 1


def test_supplier_deactivated_event_to_dict():
    event = SupplierDeactivated(
        aggregate_id=1, supplier_id=1, reason="No longer needed"
    )
    d = event.to_dict()

    assert d["event_type"] == "SupplierDeactivated"
    assert d["payload"]["supplier_id"] == 1
    assert d["payload"]["reason"] == "No longer needed"


def test_supplier_deactivated_event_no_reason():
    event = SupplierDeactivated(aggregate_id=1, supplier_id=1)
    d = event.to_dict()

    assert d["event_type"] == "SupplierDeactivated"
    assert d["payload"]["reason"] is None


def test_supplier_created_event_is_published():
    from unittest.mock import MagicMock

    from src.shared.domain.tax import TaxType
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher
    from src.suppliers.app.commands.supplier import (
        CreateSupplierCommand,
        CreateSupplierCommandHandler,
    )
    from src.suppliers.domain.entities import Supplier

    supplier = Supplier(
        id=1,
        name="ACME Corp",
        tax_id="1710034065001",
        tax_type=TaxType.RUC,
        is_active=True,
    )
    repo = MagicMock()
    repo.create.return_value = supplier

    events_received = []
    EventBus.subscribe(SupplierCreated, lambda e: events_received.append(e))

    handler = CreateSupplierCommandHandler(repo, EventBusPublisher())
    handler.handle(
        CreateSupplierCommand(name="ACME Corp", tax_id="1710034065001", tax_type=1)
    )

    assert len(events_received) == 1
    assert events_received[0].supplier_id == 1


def test_supplier_activated_event_is_published():
    from unittest.mock import MagicMock

    from src.shared.domain.tax import TaxType
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher
    from src.suppliers.app.commands.supplier import (
        ActivateSupplierCommand,
        ActivateSupplierCommandHandler,
    )
    from src.suppliers.domain.entities import Supplier

    supplier = Supplier(
        id=1,
        name="ACME Corp",
        tax_id="1710034065001",
        tax_type=TaxType.RUC,
        is_active=False,
    )
    activated = Supplier(
        id=1,
        name="ACME Corp",
        tax_id="1710034065001",
        tax_type=TaxType.RUC,
        is_active=True,
    )
    repo = MagicMock()
    repo.get_by_id.return_value = supplier
    repo.update.return_value = activated

    events_received = []
    EventBus.subscribe(SupplierActivated, lambda e: events_received.append(e))

    handler = ActivateSupplierCommandHandler(repo, EventBusPublisher())
    handler.handle(ActivateSupplierCommand(id=1))

    assert len(events_received) == 1
    assert events_received[0].supplier_id == 1
