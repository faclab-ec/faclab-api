from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.customers.domain.entities import TaxType
from src.shared.domain.exceptions import NotFoundError
from src.suppliers.app.commands.supplier import (
    ActivateSupplierCommand,
    ActivateSupplierCommandHandler,
    CreateSupplierCommand,
    CreateSupplierCommandHandler,
    DeactivateSupplierCommand,
    DeactivateSupplierCommandHandler,
    DeleteSupplierCommand,
    DeleteSupplierCommandHandler,
    UpdateSupplierCommand,
    UpdateSupplierCommandHandler,
)
from src.suppliers.app.commands.supplier_contact import (
    CreateSupplierContactCommand,
    CreateSupplierContactCommandHandler,
    DeleteSupplierContactCommand,
    DeleteSupplierContactCommandHandler,
    UpdateSupplierContactCommand,
    UpdateSupplierContactCommandHandler,
)
from src.suppliers.app.commands.supplier_product import (
    CreateSupplierProductCommand,
    CreateSupplierProductCommandHandler,
    DeleteSupplierProductCommand,
    DeleteSupplierProductCommandHandler,
    UpdateSupplierProductCommand,
    UpdateSupplierProductCommandHandler,
)
from src.suppliers.domain.entities import Supplier, SupplierContact, SupplierProduct

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_supplier(**overrides) -> Supplier:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "ACME Corp",
        "tax_id": "1710034065001",
        "tax_type": TaxType.RUC,
        "is_active": True,
    }
    defaults.update(overrides)
    return Supplier(**defaults)


def _make_contact(**overrides) -> SupplierContact:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 1,
        "name": "Jane Doe",
    }
    defaults.update(overrides)
    return SupplierContact(**defaults)


def _make_supplier_product(**overrides) -> SupplierProduct:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 1,
        "product_id": 10,
        "purchase_price": Decimal("25.00"),
    }
    defaults.update(overrides)
    return SupplierProduct(**defaults)


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------


def test_create_supplier_command_handler():
    supplier = _make_supplier()
    repo = MagicMock()
    repo.create.return_value = supplier
    handler = CreateSupplierCommandHandler(repo, MagicMock())

    command = CreateSupplierCommand(
        name="ACME Corp",
        tax_id="1710034065001",
        tax_type=1,
    )
    result = handler.handle(command)

    repo.create.assert_called_once()
    assert result["name"] == "ACME Corp"
    assert result["tax_id"] == "1710034065001"


def test_create_supplier_publishes_event():
    from src.shared.infra.events.event_bus import EventBus
    from src.shared.infra.events.event_bus_publisher import EventBusPublisher
    from src.suppliers.domain.events import SupplierCreated

    EventBus.clear()
    supplier = _make_supplier()
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
    assert events_received[0].name == "ACME Corp"
    EventBus.clear()


def test_create_supplier_invalid_email_raises():
    repo = MagicMock()
    handler = CreateSupplierCommandHandler(repo, MagicMock())

    command = CreateSupplierCommand(
        name="ACME Corp",
        tax_id="1710034065001",
        email="not-an-email",
    )
    with pytest.raises(ValueError, match="Invalid email"):
        handler.handle(command)


def test_create_supplier_invalid_tax_id_raises():
    repo = MagicMock()
    handler = CreateSupplierCommandHandler(repo, MagicMock())

    command = CreateSupplierCommand(
        name="ACME Corp",
        tax_id="123",  # Too short for EC RUC
    )
    with pytest.raises(ValueError, match="Invalid tax ID"):
        handler.handle(command)


def test_update_supplier_command_handler():
    supplier = _make_supplier(name="Updated Corp")
    repo = MagicMock()
    repo.update.return_value = supplier
    handler = UpdateSupplierCommandHandler(repo)

    command = UpdateSupplierCommand(
        id=1,
        name="Updated Corp",
        tax_id="1710034065001",
        tax_type=1,
    )
    result = handler.handle(command)

    repo.update.assert_called_once()
    assert result["name"] == "Updated Corp"


def test_update_supplier_invalid_email_raises():
    repo = MagicMock()
    handler = UpdateSupplierCommandHandler(repo)

    command = UpdateSupplierCommand(
        id=1,
        name="ACME Corp",
        tax_id="1710034065001",
        email="not-an-email",
    )
    with pytest.raises(ValueError, match="Invalid email"):
        handler.handle(command)


def test_update_supplier_invalid_tax_id_raises():
    repo = MagicMock()
    handler = UpdateSupplierCommandHandler(repo)

    command = UpdateSupplierCommand(
        id=1,
        name="ACME Corp",
        tax_id="123",  # Too short for EC RUC
    )
    with pytest.raises(ValueError, match="Invalid tax ID"):
        handler.handle(command)


def test_delete_supplier_command_handler():
    repo = MagicMock()
    handler = DeleteSupplierCommandHandler(repo)

    handler.handle(DeleteSupplierCommand(id=1))

    repo.delete.assert_called_once_with(1)


def test_activate_supplier_command_handler():
    supplier = _make_supplier(is_active=False)
    activated = _make_supplier(is_active=True)
    repo = MagicMock()
    repo.get_by_id.return_value = supplier
    repo.update.return_value = activated
    handler = ActivateSupplierCommandHandler(repo, MagicMock())

    result = handler.handle(ActivateSupplierCommand(id=1))

    repo.update.assert_called_once()
    assert result["is_active"] is True


def test_activate_supplier_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = ActivateSupplierCommandHandler(repo, MagicMock())

    with pytest.raises(NotFoundError, match="Supplier with id 1 not found"):
        handler.handle(ActivateSupplierCommand(id=1))


def test_deactivate_supplier_command_handler():
    supplier = _make_supplier(is_active=True)
    deactivated = _make_supplier(is_active=False)
    repo = MagicMock()
    repo.get_by_id.return_value = supplier
    repo.update.return_value = deactivated
    handler = DeactivateSupplierCommandHandler(repo, MagicMock())

    result = handler.handle(DeactivateSupplierCommand(id=1))

    repo.update.assert_called_once()
    assert result["is_active"] is False


def test_deactivate_supplier_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = DeactivateSupplierCommandHandler(repo, MagicMock())

    with pytest.raises(NotFoundError, match="Supplier with id 1 not found"):
        handler.handle(DeactivateSupplierCommand(id=1))


# ---------------------------------------------------------------------------
# SupplierContact CRUD
# ---------------------------------------------------------------------------


def test_create_supplier_contact_command_handler():
    contact = _make_contact()
    repo = MagicMock()
    repo.create.return_value = contact
    handler = CreateSupplierContactCommandHandler(repo)

    result = handler.handle(
        CreateSupplierContactCommand(supplier_id=1, name="Jane Doe", role="Sales")
    )

    repo.create.assert_called_once()
    assert result["name"] == "Jane Doe"
    assert result["supplier_id"] == 1


def test_update_supplier_contact_command_handler():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_contact(supplier_id=7)
    repo.update.side_effect = lambda c: c
    handler = UpdateSupplierContactCommandHandler(repo)

    result = handler.handle(UpdateSupplierContactCommand(id=1, name="Updated Name"))

    repo.update.assert_called_once()
    assert result["name"] == "Updated Name"
    assert result["supplier_id"] == 7


def test_update_supplier_contact_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateSupplierContactCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateSupplierContactCommand(id=99, name="X"))

    repo.update.assert_not_called()


def test_delete_supplier_contact_command_handler():
    repo = MagicMock()
    handler = DeleteSupplierContactCommandHandler(repo)

    handler.handle(DeleteSupplierContactCommand(id=1))

    repo.delete.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# SupplierProduct CRUD
# ---------------------------------------------------------------------------


def test_create_supplier_product_command_handler():
    sp = _make_supplier_product()
    repo = MagicMock()
    repo.create.return_value = sp
    handler = CreateSupplierProductCommandHandler(repo)

    result = handler.handle(
        CreateSupplierProductCommand(
            supplier_id=1,
            product_id=10,
            purchase_price=Decimal("25.00"),
        )
    )

    repo.create.assert_called_once()
    assert result["supplier_id"] == 1
    assert result["product_id"] == 10
    assert result["purchase_price"] == Decimal("25.00")


def test_update_supplier_product_command_handler():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_supplier_product(supplier_id=4)
    repo.update.side_effect = lambda sp: sp
    handler = UpdateSupplierProductCommandHandler(repo)

    result = handler.handle(
        UpdateSupplierProductCommand(
            id=1,
            product_id=10,
            purchase_price=Decimal("30.00"),
        )
    )

    repo.update.assert_called_once()
    assert result["purchase_price"] == Decimal("30.00")
    assert result["supplier_id"] == 4


def test_update_supplier_product_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateSupplierProductCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateSupplierProductCommand(id=99, product_id=10))

    repo.update.assert_not_called()


def test_delete_supplier_product_command_handler():
    repo = MagicMock()
    handler = DeleteSupplierProductCommandHandler(repo)

    handler.handle(DeleteSupplierProductCommand(id=1))

    repo.delete.assert_called_once_with(1)
