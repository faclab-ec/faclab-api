"""Unit tests for POS quick customer creation."""

from unittest.mock import Mock

from src.customers.app.commands.customer import (
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
)
from src.pos.infra.validators import QuickCustomerRequest


def test_quick_customer_request_minimal_fields():
    """Test QuickCustomerRequest accepts minimal fields."""
    request = QuickCustomerRequest.model_validate(
        {"name": "Juan Perez", "taxId": "0912345678", "taxType": 2}
    )

    assert request.name == "Juan Perez"
    assert request.tax_id == "0912345678"
    assert request.tax_type == 2


def test_quick_customer_request_default_tax_type():
    """Test QuickCustomerRequest defaults tax_type to 1 (RUC)."""
    request = QuickCustomerRequest.model_validate(
        {"name": "Empresa SA", "taxId": "0912345678001"}
    )

    assert request.tax_type == 1


def test_quick_customer_request_snake_case():
    """Test QuickCustomerRequest accepts snake_case fields."""
    request = QuickCustomerRequest.model_validate(
        {"name": "Test", "tax_id": "1234567890", "tax_type": 3}
    )

    assert request.tax_id == "1234567890"
    assert request.tax_type == 3


def test_quick_customer_handler_creates_customer():
    """Test that quick customer creation delegates to CreateCustomerCommandHandler."""
    mock_repo = Mock()
    mock_event_publisher = Mock()

    mock_repo.create.return_value = Mock(
        dict=lambda: {
            "id": 1,
            "name": "Juan Perez",
            "tax_id": "0912345678",
            "tax_type": 2,
            "email": None,
            "phone": None,
            "address": None,
            "city": None,
            "state": None,
            "country": None,
            "credit_limit": None,
            "payment_terms": None,
            "is_active": True,
        }
    )

    handler = CreateCustomerCommandHandler(mock_repo, mock_event_publisher)
    command = CreateCustomerCommand(
        name="Juan Perez",
        tax_id="0912345678",
        tax_type=3,
    )
    result = handler.handle(command)

    assert result["name"] == "Juan Perez"
    assert result["tax_id"] == "0912345678"
    mock_repo.create.assert_called_once()
