from typing import Any
from unittest.mock import MagicMock

import pytest

from src.customers.app.commands.customer_contact import (
    CreateCustomerContactCommand,
    CreateCustomerContactCommandHandler,
    DeleteCustomerContactCommand,
    DeleteCustomerContactCommandHandler,
    UpdateCustomerContactCommand,
    UpdateCustomerContactCommandHandler,
)
from src.customers.domain.entities import CustomerContact
from src.shared.domain.exceptions import NotFoundError


def _make_contact(**overrides) -> CustomerContact:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 1,
        "name": "Jane Doe",
    }
    defaults.update(overrides)
    return CustomerContact(**defaults)


def test_create_customer_contact():
    repo = MagicMock()
    repo.create.side_effect = lambda c: c
    handler = CreateCustomerContactCommandHandler(repo)

    result = handler.handle(
        CreateCustomerContactCommand(customer_id=3, name="Jane Doe", role="Buyer")
    )

    repo.create.assert_called_once()
    assert result["customer_id"] == 3
    assert result["role"] == "Buyer"


def test_update_customer_contact_keeps_customer_id():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_contact(customer_id=7)
    repo.update.side_effect = lambda c: c
    handler = UpdateCustomerContactCommandHandler(repo)

    result = handler.handle(
        UpdateCustomerContactCommand(id=1, name="Updated", email="jane@example.com")
    )

    repo.update.assert_called_once()
    assert result["customer_id"] == 7
    assert result["name"] == "Updated"
    assert result["email"] == "jane@example.com"


def test_update_customer_contact_not_found():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = UpdateCustomerContactCommandHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(UpdateCustomerContactCommand(id=99, name="X"))

    repo.update.assert_not_called()


def test_delete_customer_contact():
    repo = MagicMock()
    handler = DeleteCustomerContactCommandHandler(repo)

    handler.handle(DeleteCustomerContactCommand(id=1))

    repo.delete.assert_called_once_with(1)
