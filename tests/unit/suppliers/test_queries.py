from decimal import Decimal
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest

from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxType
from src.suppliers.app.queries.supplier import (
    GetAllSuppliersQuery,
    GetAllSuppliersQueryHandler,
    GetSupplierByIdQuery,
    GetSupplierByIdQueryHandler,
)
from src.suppliers.app.queries.supplier_contact import (
    GetContactsBySupplierIdQuery,
    GetContactsBySupplierIdQueryHandler,
    GetSupplierContactByIdQuery,
    GetSupplierContactByIdQueryHandler,
)
from src.suppliers.app.queries.supplier_product import (
    GetProductSuppliersByProductIdQuery,
    GetProductSuppliersByProductIdQueryHandler,
    GetSupplierProductByIdQuery,
    GetSupplierProductByIdQueryHandler,
    GetSupplierProductsBySupplierIdQuery,
    GetSupplierProductsBySupplierIdQueryHandler,
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
# Supplier queries
# ---------------------------------------------------------------------------


def test_get_all_suppliers_no_filter():
    suppliers = [_make_supplier(id=1), _make_supplier(id=2, name="Beta Supplies")]
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in suppliers],
    }
    handler = GetAllSuppliersQueryHandler(repo)

    result = handler.handle(GetAllSuppliersQuery())

    repo.paginate_by_spec.assert_called_once_with(ANY, limit=None, offset=None)
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "ACME Corp"
    assert result["items"][1]["name"] == "Beta Supplies"
    assert result["total"] == 2


def test_get_all_suppliers_with_active_filter():
    active_supplier = _make_supplier(is_active=True)
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [active_supplier.dict()],
    }
    handler = GetAllSuppliersQueryHandler(repo)

    result = handler.handle(GetAllSuppliersQuery(is_active=True))

    spec = repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(_make_supplier(is_active=True))
    assert not spec.is_satisfied_by(_make_supplier(is_active=False))
    assert len(result["items"]) == 1
    assert result["items"][0]["is_active"] is True
    assert result["total"] == 1


def test_get_all_suppliers_with_search():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {"total": 0, "items": []}

    GetAllSuppliersQueryHandler(repo).handle(
        GetAllSuppliersQuery(is_active=True, search="acme")
    )

    spec = repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(_make_supplier(name="ACME Corp", is_active=True))
    assert spec.is_satisfied_by(
        _make_supplier(name="Otro", tax_id="ACME-1", is_active=True)
    )
    assert not spec.is_satisfied_by(_make_supplier(name="ACME Corp", is_active=False))
    assert not spec.is_satisfied_by(_make_supplier(name="Beta", is_active=True))


def test_get_all_suppliers_with_inactive_filter():
    inactive_supplier = _make_supplier(is_active=False)
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [inactive_supplier.dict()],
    }
    handler = GetAllSuppliersQueryHandler(repo)

    result = handler.handle(GetAllSuppliersQuery(is_active=False))

    spec = repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(_make_supplier(is_active=False))
    assert not spec.is_satisfied_by(_make_supplier(is_active=True))
    assert len(result["items"]) == 1
    assert result["items"][0]["is_active"] is False
    assert result["total"] == 1


def test_get_supplier_by_id_handler():
    supplier = _make_supplier()
    repo = MagicMock()
    repo.get_by_id.return_value = supplier
    handler = GetSupplierByIdQueryHandler(repo)

    result = handler.handle(GetSupplierByIdQuery(id=1))

    assert result["id"] == 1
    assert result["name"] == "ACME Corp"


def test_get_supplier_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetSupplierByIdQueryHandler(repo)

    with pytest.raises(NotFoundError, match="Supplier with id 999 not found"):
        handler.handle(GetSupplierByIdQuery(id=999))


# ---------------------------------------------------------------------------
# SupplierContact queries
# ---------------------------------------------------------------------------


def test_get_contacts_by_supplier_id_handler():
    contacts = [_make_contact(id=1), _make_contact(id=2, name="John Smith")]
    repo = MagicMock()
    repo.filter_by.return_value = contacts
    handler = GetContactsBySupplierIdQueryHandler(repo)

    result = handler.handle(GetContactsBySupplierIdQuery(supplier_id=1))

    repo.filter_by.assert_called_once_with(supplier_id=1)
    assert len(result) == 2
    assert result[0]["name"] == "Jane Doe"
    assert result[1]["name"] == "John Smith"


def test_get_supplier_contact_by_id_handler():
    contact = _make_contact()
    repo = MagicMock()
    repo.get_by_id.return_value = contact
    handler = GetSupplierContactByIdQueryHandler(repo)

    result = handler.handle(GetSupplierContactByIdQuery(id=1))

    assert result["id"] == 1
    assert result["name"] == "Jane Doe"


def test_get_supplier_contact_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetSupplierContactByIdQueryHandler(repo)

    with pytest.raises(NotFoundError, match="Supplier contact with id 99 not found"):
        handler.handle(GetSupplierContactByIdQuery(id=99))


# ---------------------------------------------------------------------------
# SupplierProduct queries
# ---------------------------------------------------------------------------


def test_get_supplier_products_by_supplier_id_handler():
    products = [
        _make_supplier_product(id=1),
        _make_supplier_product(id=2, product_id=20),
    ]
    repo = MagicMock()
    repo.filter_by.return_value = products
    handler = GetSupplierProductsBySupplierIdQueryHandler(repo, MagicMock())

    result = handler.handle(GetSupplierProductsBySupplierIdQuery(supplier_id=1))

    repo.filter_by.assert_called_once_with(supplier_id=1)
    assert len(result) == 2


def test_get_product_suppliers_by_product_id_handler():
    products = [
        _make_supplier_product(id=1),
        _make_supplier_product(id=3, supplier_id=2),
    ]
    repo = MagicMock()
    repo.filter_by.return_value = products
    handler = GetProductSuppliersByProductIdQueryHandler(repo)

    result = handler.handle(GetProductSuppliersByProductIdQuery(product_id=10))

    repo.filter_by.assert_called_once_with(product_id=10)
    assert len(result) == 2


def test_get_supplier_product_by_id_handler():
    sp = _make_supplier_product()
    repo = MagicMock()
    repo.get_by_id.return_value = sp
    handler = GetSupplierProductByIdQueryHandler(repo)

    result = handler.handle(GetSupplierProductByIdQuery(id=1))

    assert result["id"] == 1
    assert result["purchase_price"] == Decimal("25.00")


def test_get_supplier_product_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetSupplierProductByIdQueryHandler(repo)

    with pytest.raises(NotFoundError, match="Supplier product with id 99 not found"):
        handler.handle(GetSupplierProductByIdQuery(id=99))
