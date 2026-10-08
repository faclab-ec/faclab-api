from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.sales.app.commands.create_sale import (
    CreateSaleCommand,
    CreateSaleCommandHandler,
)
from src.sales.domain.entities import Sale, SaleStatus
from src.shared.domain.exceptions import DomainError


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": None,
        "is_final_consumer": True,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _mock_repo(entity=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
    return repo


def test_create_sale_final_consumer():
    """Test crear venta como consumidor final"""
    sale = _make_sale()
    repo = _mock_repo(entity=sale)
    event_publisher = MagicMock()
    handler = CreateSaleCommandHandler(repo, event_publisher)

    command = CreateSaleCommand(is_final_consumer=True)
    result = handler.handle(command)

    repo.create.assert_called_once()
    created_sale = repo.create.call_args[0][0]
    assert created_sale.is_final_consumer is True
    assert created_sale.customer_id is None
    assert result["is_final_consumer"] is True


def test_create_sale_final_consumer_ignores_customer_id():
    """Test que consumidor final fuerza customer_id a None"""
    sale = _make_sale()
    repo = _mock_repo(entity=sale)
    event_publisher = MagicMock()
    handler = CreateSaleCommandHandler(repo, event_publisher)

    command = CreateSaleCommand(customer_id=10, is_final_consumer=True)
    handler.handle(command)

    created_sale = repo.create.call_args[0][0]
    assert created_sale.customer_id is None


def test_create_sale_requires_customer_when_not_final_consumer():
    """Test que customer_id es requerido cuando no es consumidor final"""
    repo = _mock_repo()
    event_publisher = MagicMock()
    handler = CreateSaleCommandHandler(repo, event_publisher)

    with pytest.raises(DomainError):
        handler.handle(CreateSaleCommand(is_final_consumer=False))
