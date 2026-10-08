from typing import Any

from src.customers.domain.entities import Customer
from src.customers.domain.specifications import ActiveCustomers, CustomersByType
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


def test_active_customers_spec():
    spec = ActiveCustomers()

    active = _make_customer(is_active=True)
    inactive = _make_customer(is_active=False)

    assert spec.is_satisfied_by(active) is True
    assert spec.is_satisfied_by(inactive) is False


def test_active_customers_sql_criteria():
    spec = ActiveCustomers()
    criteria = spec.to_query_criteria()

    assert len(criteria) == 1


def test_customers_by_type_spec():
    spec = CustomersByType(tax_type=1)

    ruc_customer = _make_customer(tax_type=TaxType.RUC)
    passport_customer = _make_customer(tax_type=TaxType.PASSPORT)

    assert spec.is_satisfied_by(ruc_customer) is True
    assert spec.is_satisfied_by(passport_customer) is False


def test_customers_by_type_sql_criteria():
    spec = CustomersByType(tax_type=2)
    criteria = spec.to_query_criteria()

    assert len(criteria) == 1


def test_combined_specs():
    active_spec = ActiveCustomers()
    type_spec = CustomersByType(tax_type=1)
    combined = active_spec & type_spec

    active_ruc = _make_customer(is_active=True, tax_type=TaxType.RUC)
    inactive_ruc = _make_customer(is_active=False, tax_type=TaxType.RUC)
    active_passport = _make_customer(is_active=True, tax_type=TaxType.PASSPORT)

    assert combined.is_satisfied_by(active_ruc) is True
    assert combined.is_satisfied_by(inactive_ruc) is False
    assert combined.is_satisfied_by(active_passport) is False
