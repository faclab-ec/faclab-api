from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.customers.domain.entities import Customer
from src.sales.app.queries import (
    GetAllSalesQuery,
    GetAllSalesQueryHandler,
    GetSaleByIdQuery,
    GetSaleByIdQueryHandler,
    GetSaleItemsQuery,
    GetSaleItemsQueryHandler,
    GetSalePaymentsQuery,
    GetSalePaymentsQueryHandler,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem, SaleStatus
from src.shared.domain.exceptions import NotFoundError


def _make_sale(**overrides) -> Sale:
    defaults: dict[str, Any] = {
        "id": 1,
        "customer_id": 10,
        "status": SaleStatus.DRAFT,
        "subtotal": Decimal("0"),
        "total": Decimal("0"),
    }
    defaults.update(overrides)
    return Sale(**defaults)


def _make_sale_item(**overrides) -> SaleItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "product_id": 100,
        "quantity": 10,
        "unit_price": Decimal("100.00"),
        "discount": Decimal("0"),
    }
    defaults.update(overrides)
    return SaleItem(**defaults)


def _make_payment(**overrides) -> Payment:
    defaults: dict[str, Any] = {
        "id": 1,
        "sale_id": 1,
        "amount": Decimal("500.00"),
        "payment_method": PaymentMethod.CASH,
    }
    defaults.update(overrides)
    return Payment(**defaults)


def _mock_repo(entity=None, entities=None):
    repo = MagicMock()
    if entity is not None:
        repo.get_by_id.return_value = entity
    if entities is not None:
        repo.filter_by.return_value = entities
        repo.get_all.return_value = entities
    return repo


def _customer_repo(*customers: Customer) -> MagicMock:
    by_id = {c.id: c for c in customers}
    repo = MagicMock()
    repo.get_by_ids.side_effect = lambda ids: [by_id[i] for i in ids if i in by_id]
    repo.get_by_id.side_effect = by_id.get
    return repo


def test_get_all_sales_query_handler():
    """Test obtener todas las ventas"""
    sales = [
        _make_sale(id=1, customer_id=10),
        _make_sale(id=2, customer_id=20),
    ]
    repo = _mock_repo(entities=sales)
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in sales],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery()
    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2
    assert result["total"] == 2
    repo.paginate.assert_called_once_with(limit=None, offset=None)


def test_get_all_sales_with_customer_filter():
    """Test filtrar ventas por cliente"""
    sales = [_make_sale(id=1, customer_id=10)]
    repo = _mock_repo(entities=sales)
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in sales],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery(customer_id=10)
    result = handler.handle(query)

    repo.paginate.assert_called_once_with(limit=None, offset=None, customer_id=10)
    assert len(result["items"]) == 1
    assert result["items"][0]["customer_id"] == 10
    assert result["total"] == 1


def test_get_all_sales_with_status_filter():
    """Test filtrar ventas por estado"""
    sales = [_make_sale(id=1, status=SaleStatus.CONFIRMED)]
    repo = _mock_repo(entities=sales)
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [s.dict() for s in sales],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery(status="CONFIRMED")
    result = handler.handle(query)

    repo.paginate.assert_called_once_with(limit=None, offset=None, status="CONFIRMED")
    assert len(result["items"]) == 1
    assert result["total"] == 1


def test_get_all_sales_with_pagination():
    """Test paginacion de ventas"""
    sales = [_make_sale(id=i) for i in range(1, 6)]
    repo = _mock_repo(entities=sales)
    repo.paginate.return_value = {
        "total": 10,
        "limit": 5,
        "offset": 0,
        "items": [s.dict() for s in sales],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery(limit=5, offset=0)
    result = handler.handle(query)

    repo.paginate.assert_called_once_with(limit=5, offset=0)
    assert len(result["items"]) == 5
    assert result["total"] == 10


def test_get_all_sales_empty():
    """Test obtener ventas cuando no hay ninguna"""
    repo = _mock_repo(entities=[])
    repo.paginate.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery()
    result = handler.handle(query)

    repo.paginate.assert_called_once_with(limit=None, offset=None)
    assert len(result["items"]) == 0
    assert result["total"] == 0


def test_get_sale_by_id_query_handler():
    """Test obtener una venta por ID"""
    sale = _make_sale(id=1, customer_id=10)
    repo = _mock_repo(entity=sale)
    handler = GetSaleByIdQueryHandler(repo, _customer_repo())

    query = GetSaleByIdQuery(sale_id=1)
    result = handler.handle(query)

    repo.get_by_id.assert_called_once_with(1)
    assert result is not None
    assert result["id"] == 1
    assert result["customer_id"] == 10


def test_get_all_sales_adds_customer_name():
    sales = [
        _make_sale(id=1, customer_id=10),
        _make_sale(id=2, customer_id=None, is_final_consumer=True),
    ]
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [sale.dict() for sale in sales],
    }
    customers = _customer_repo(Customer(id=10, name="Ana Pérez", tax_id="0102030405"))
    handler = GetAllSalesQueryHandler(repo, customers)

    result = handler.handle(GetAllSalesQuery())

    assert [s["customer_name"] for s in result["items"]] == ["Ana Pérez", None]


def test_get_sale_by_id_adds_customer_name():
    repo = _mock_repo(entity=_make_sale(id=1, customer_id=10))
    customers = _customer_repo(Customer(id=10, name="Ana Pérez", tax_id="0102030405"))
    handler = GetSaleByIdQueryHandler(repo, customers)

    result = handler.handle(GetSaleByIdQuery(sale_id=1))

    assert result["customer_name"] == "Ana Pérez"


def test_get_sale_by_id_final_consumer_has_no_customer_name():
    repo = _mock_repo(entity=_make_sale(id=1, customer_id=None))
    customers = _customer_repo()
    handler = GetSaleByIdQueryHandler(repo, customers)

    result = handler.handle(GetSaleByIdQuery(sale_id=1))

    assert result["customer_name"] is None
    customers.get_by_id.assert_not_called()


def test_get_sale_by_id_not_found():
    """Test obtener una venta que no existe lanza NotFoundError"""
    repo = _mock_repo()
    repo.get_by_id.return_value = None
    handler = GetSaleByIdQueryHandler(repo, _customer_repo())

    with pytest.raises(NotFoundError):
        handler.handle(GetSaleByIdQuery(sale_id=999))


def test_get_sale_items_query_handler():
    """Test obtener items de una venta"""
    items = [
        _make_sale_item(id=1, product_id=100, quantity=10),
        _make_sale_item(id=2, product_id=200, quantity=5),
    ]
    repo = _mock_repo(entities=items)
    handler = GetSaleItemsQueryHandler(repo, MagicMock())

    query = GetSaleItemsQuery(sale_id=1)
    result = handler.handle(query)

    repo.filter_by.assert_called_once_with(sale_id=1)
    assert len(result) == 2
    assert result[0]["product_id"] == 100
    assert result[1]["product_id"] == 200


def test_get_sale_items_empty():
    """Test obtener items de una venta sin items"""
    repo = _mock_repo(entities=[])
    handler = GetSaleItemsQueryHandler(repo, MagicMock())

    query = GetSaleItemsQuery(sale_id=1)
    result = handler.handle(query)

    assert len(result) == 0


def test_get_sale_payments_query_handler():
    """Test obtener pagos de una venta"""
    payments = [
        _make_payment(id=1, amount=Decimal("500.00")),
        _make_payment(id=2, amount=Decimal("300.00")),
    ]
    repo = _mock_repo(entities=payments)
    handler = GetSalePaymentsQueryHandler(repo)

    query = GetSalePaymentsQuery(sale_id=1)
    result = handler.handle(query)

    repo.filter_by.assert_called_once_with(sale_id=1)
    assert len(result) == 2
    assert result[0]["amount"] == Decimal("500.00")
    assert result[1]["amount"] == Decimal("300.00")


def test_get_sale_payments_empty():
    """Test obtener pagos de una venta sin pagos"""
    repo = _mock_repo(entities=[])
    handler = GetSalePaymentsQueryHandler(repo)

    query = GetSalePaymentsQuery(sale_id=1)
    result = handler.handle(query)

    assert len(result) == 0


def test_get_all_sales_multiple_filters():
    """Test filtrar ventas con multiples criterios"""
    sales = [_make_sale(id=1, customer_id=10, status=SaleStatus.CONFIRMED)]
    repo = _mock_repo(entities=sales)
    repo.paginate.return_value = {
        "total": 1,
        "limit": 10,
        "offset": None,
        "items": [s.dict() for s in sales],
    }
    handler = GetAllSalesQueryHandler(repo, _customer_repo())

    query = GetAllSalesQuery(customer_id=10, status="CONFIRMED", limit=10)
    handler.handle(query)

    # Verificar que se aplicaron los filtros
    call_kwargs = repo.paginate.call_args[1]
    assert call_kwargs["customer_id"] == 10
    assert call_kwargs["status"] == "CONFIRMED"
    assert call_kwargs["limit"] == 10
