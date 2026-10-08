from typing import Any
from unittest.mock import MagicMock

import pytest

from src.customers.app.queries.customer import (
    GetAllCustomersQuery,
    GetAllCustomersQueryHandler,
    GetCustomerByIdQuery,
    GetCustomerByIdQueryHandler,
    GetCustomerByTaxIdQuery,
    GetCustomerByTaxIdQueryHandler,
)
from src.customers.domain.entities import Customer, TaxType
from src.shared.domain.exceptions import NotFoundError


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


def test_get_all_customers_query_handler():
    customers = [_make_customer(id=1), _make_customer(id=2, name="Second")]
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [c.dict() for c in customers],
    }
    handler = GetAllCustomersQueryHandler(repo)

    result = handler.handle(GetAllCustomersQuery())

    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "Test Customer"
    assert result["items"][1]["name"] == "Second"
    assert result["total"] == 2


def test_get_customer_by_id_handler():
    customer = _make_customer()
    repo = MagicMock()
    repo.get_by_id.return_value = customer
    handler = GetCustomerByIdQueryHandler(repo)

    result = handler.handle(GetCustomerByIdQuery(id=1))

    assert result is not None
    assert result["id"] == 1
    assert result["name"] == "Test Customer"


def test_get_customer_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetCustomerByIdQueryHandler(repo)

    with pytest.raises(NotFoundError):
        handler.handle(GetCustomerByIdQuery(id=999))


def test_get_customer_by_tax_id_handler():
    customer = _make_customer()
    repo = MagicMock()
    repo.first.return_value = customer
    handler = GetCustomerByTaxIdQueryHandler(repo)

    result = handler.handle(GetCustomerByTaxIdQuery(tax_id="1710034065001"))

    assert result is not None
    assert result["tax_id"] == "1710034065001"
