from typing import Any
from unittest.mock import MagicMock

import pytest

from src.customers.app.commands.customer import (
    ActivateCustomerCommand,
    ActivateCustomerCommandHandler,
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
    DeactivateCustomerCommand,
    DeactivateCustomerCommandHandler,
    DeleteCustomerCommand,
    DeleteCustomerCommandHandler,
    UpdateCustomerCommand,
    UpdateCustomerCommandHandler,
)
from src.customers.domain.entities import Customer
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxType


def _make_customer(**overrides) -> Customer:
    defaults: dict[str, Any] = {
        "id": 1,
        "name": "Test Customer",
        "tax_id": "1710034065001",
        "tax_type": TaxType.RUC,
        "is_active": True,
    }
    defaults.update(overrides)
    return Customer(**defaults)


def _mock_repo(customer=None, customers=None):
    repo = MagicMock()
    if customer is not None:
        repo.create.return_value = customer
        repo.update.return_value = customer
        repo.get_by_id.return_value = customer
    if customers is not None:
        repo.get_all.return_value = customers
    return repo


def test_create_customer_command_handler():
    customer = _make_customer()
    repo = _mock_repo(customer=customer)
    handler = CreateCustomerCommandHandler(repo, MagicMock())

    command = CreateCustomerCommand(
        name="Test Customer",
        tax_id="1710034065001",
        tax_type=1,
    )
    result = handler.handle(command)

    repo.create.assert_called_once()
    assert result["name"] == "Test Customer"
    assert result["tax_id"] == "1710034065001"


def test_create_customer_invalid_email_raises():
    repo = _mock_repo(customer=_make_customer())
    handler = CreateCustomerCommandHandler(repo, MagicMock())

    command = CreateCustomerCommand(
        name="Test",
        tax_id="1710034065001",
        email="not-an-email",
    )
    with pytest.raises(ValueError, match="Invalid email"):
        handler.handle(command)


def test_create_customer_invalid_tax_id_raises():
    repo = _mock_repo(customer=_make_customer())
    handler = CreateCustomerCommandHandler(repo, MagicMock())

    command = CreateCustomerCommand(
        name="Test",
        tax_id="123",  # Too short for EC RUC
    )
    with pytest.raises(ValueError, match="Invalid tax ID"):
        handler.handle(command)


def test_update_customer_command_handler():
    customer = _make_customer(name="Updated Name")
    repo = _mock_repo(customer=customer)
    handler = UpdateCustomerCommandHandler(repo, MagicMock())

    command = UpdateCustomerCommand(
        id=1,
        name="Updated Name",
        tax_id="1710034065001",
        tax_type=1,
    )
    result = handler.handle(command)

    repo.update.assert_called_once()
    assert result["name"] == "Updated Name"


def test_delete_customer_command_handler():
    repo = _mock_repo()
    handler = DeleteCustomerCommandHandler(repo)

    handler.handle(DeleteCustomerCommand(id=1))

    repo.delete.assert_called_once_with(1)


def test_activate_customer_command_handler():
    customer = _make_customer(is_active=False)
    activated = _make_customer(is_active=True)
    repo = MagicMock()
    repo.get_by_id.return_value = customer
    repo.update.return_value = activated
    handler = ActivateCustomerCommandHandler(repo, MagicMock())

    result = handler.handle(ActivateCustomerCommand(id=1))

    repo.update.assert_called_once()
    assert result["is_active"] is True


def test_activate_customer_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = ActivateCustomerCommandHandler(repo, MagicMock())

    with pytest.raises(NotFoundError, match="Customer with id 1 not found"):
        handler.handle(ActivateCustomerCommand(id=1))


def test_deactivate_customer_command_handler():
    customer = _make_customer(is_active=True)
    deactivated = _make_customer(is_active=False)
    repo = MagicMock()
    repo.get_by_id.return_value = customer
    repo.update.return_value = deactivated
    handler = DeactivateCustomerCommandHandler(repo, MagicMock())

    result = handler.handle(DeactivateCustomerCommand(id=1))

    repo.update.assert_called_once()
    assert result["is_active"] is False
