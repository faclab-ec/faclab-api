from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.purchasing.app.queries.purchase_order import (
    GetAllPurchaseOrdersQuery,
    GetAllPurchaseOrdersQueryHandler,
    GetPurchaseOrderByIdQuery,
    GetPurchaseOrderByIdQueryHandler,
)
from src.purchasing.app.queries.purchase_order_item import (
    GetPurchaseOrderItemsByPOQuery,
    GetPurchaseOrderItemsByPOQueryHandler,
)
from src.purchasing.app.queries.purchase_receipt import (
    GetReceiptsByPurchaseOrderQuery,
    GetReceiptsByPurchaseOrderQueryHandler,
)
from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
)
from src.shared.domain.exceptions import NotFoundError
from src.suppliers.domain.entities import Supplier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_po(**overrides) -> PurchaseOrder:
    defaults: dict[str, Any] = {
        "id": 1,
        "supplier_id": 10,
        "order_number": "PO-2026-0001",
        "status": PurchaseOrderStatus.DRAFT,
        "subtotal": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    defaults.update(overrides)
    return PurchaseOrder(**defaults)


def _supplier_repo(*suppliers: Supplier) -> MagicMock:
    by_id = {s.id: s for s in suppliers}
    repo = MagicMock()
    repo.get_by_ids.side_effect = lambda ids: [by_id[i] for i in ids if i in by_id]
    repo.get_by_id.side_effect = by_id.get
    return repo


def _make_item(**overrides) -> PurchaseOrderItem:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
        "product_id": 5,
        "quantity_ordered": 10,
        "unit_cost": Decimal("25.00"),
        "quantity_received": 0,
    }
    defaults.update(overrides)
    return PurchaseOrderItem(**defaults)


def _make_receipt(**overrides) -> PurchaseReceipt:
    defaults: dict[str, Any] = {
        "id": 1,
        "purchase_order_id": 1,
    }
    defaults.update(overrides)
    return PurchaseReceipt(**defaults)


# ---------------------------------------------------------------------------
# GetAllPurchaseOrdersQueryHandler
# ---------------------------------------------------------------------------


def test_get_all_purchase_orders():
    po1 = _make_po(id=1)
    po2 = _make_po(id=2, order_number="PO-2026-0002")
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [po1.dict(), po2.dict()],
    }
    handler = GetAllPurchaseOrdersQueryHandler(repo, _supplier_repo())

    result = handler.handle(GetAllPurchaseOrdersQuery())

    repo.paginate.assert_called_once_with(limit=None, offset=None)
    assert len(result["items"]) == 2
    assert result["total"] == 2


def test_get_all_purchase_orders_filter_by_status():
    po = _make_po(status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [po.dict()],
    }
    handler = GetAllPurchaseOrdersQueryHandler(repo, _supplier_repo())

    result = handler.handle(GetAllPurchaseOrdersQuery(status="sent"))

    repo.paginate.assert_called_once_with(limit=None, offset=None, status="sent")
    assert len(result["items"]) == 1
    assert result["items"][0]["status"] == "sent"
    assert result["total"] == 1


def test_get_all_purchase_orders_filter_by_supplier():
    po = _make_po(supplier_id=5)
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [po.dict()],
    }
    handler = GetAllPurchaseOrdersQueryHandler(repo, _supplier_repo())

    result = handler.handle(GetAllPurchaseOrdersQuery(supplier_id=5))

    repo.paginate.assert_called_once_with(limit=None, offset=None, supplier_id=5)
    assert len(result["items"]) == 1
    assert result["total"] == 1


def test_get_all_purchase_orders_filter_by_status_and_supplier():
    po = _make_po(supplier_id=5, status=PurchaseOrderStatus.SENT)
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [po.dict()],
    }
    handler = GetAllPurchaseOrdersQueryHandler(repo, _supplier_repo())

    result = handler.handle(GetAllPurchaseOrdersQuery(status="sent", supplier_id=5))

    repo.paginate.assert_called_once_with(
        limit=None, offset=None, status="sent", supplier_id=5
    )
    assert len(result["items"]) == 1
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# GetPurchaseOrderByIdQueryHandler
# ---------------------------------------------------------------------------


def test_get_purchase_order_by_id():
    po = _make_po()
    repo = MagicMock()
    repo.get_by_id.return_value = po
    handler = GetPurchaseOrderByIdQueryHandler(repo, _supplier_repo())

    result = handler.handle(GetPurchaseOrderByIdQuery(id=1))

    assert result["id"] == 1
    assert result["order_number"] == "PO-2026-0001"


def test_get_all_purchase_orders_adds_supplier_name():
    repo = MagicMock()
    repo.paginate.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [
            _make_po(id=1, supplier_id=10).dict(),
            _make_po(id=2, supplier_id=11, order_number="PO-2026-0002").dict(),
        ],
    }
    suppliers = _supplier_repo(
        Supplier(id=10, name="Distribuidora Andina", tax_id="0990000000001")
    )
    handler = GetAllPurchaseOrdersQueryHandler(repo, suppliers)

    result = handler.handle(GetAllPurchaseOrdersQuery())

    # Supplier 11 no longer exists: the order is still listed, without a name
    assert [po["supplier_name"] for po in result["items"]] == [
        "Distribuidora Andina",
        None,
    ]


def test_get_purchase_order_by_id_adds_supplier_name():
    repo = MagicMock()
    repo.get_by_id.return_value = _make_po(supplier_id=10)
    suppliers = _supplier_repo(
        Supplier(id=10, name="Distribuidora Andina", tax_id="0990000000001")
    )
    handler = GetPurchaseOrderByIdQueryHandler(repo, suppliers)

    result = handler.handle(GetPurchaseOrderByIdQuery(id=1))

    assert result["supplier_name"] == "Distribuidora Andina"


def test_get_purchase_order_by_id_not_found_raises():
    repo = MagicMock()
    repo.get_by_id.return_value = None
    handler = GetPurchaseOrderByIdQueryHandler(repo, _supplier_repo())

    with pytest.raises(NotFoundError, match="Purchase order with id 99 not found"):
        handler.handle(GetPurchaseOrderByIdQuery(id=99))


# ---------------------------------------------------------------------------
# GetPurchaseOrderItemsByPOQueryHandler
# ---------------------------------------------------------------------------


def test_get_items_by_po():
    item1 = _make_item(id=1)
    item2 = _make_item(id=2, product_id=6)
    repo = MagicMock()
    repo.filter_by.return_value = [item1, item2]
    handler = GetPurchaseOrderItemsByPOQueryHandler(repo, MagicMock())

    result = handler.handle(GetPurchaseOrderItemsByPOQuery(purchase_order_id=1))

    repo.filter_by.assert_called_once_with(purchase_order_id=1)
    assert len(result) == 2


def test_get_items_by_po_empty():
    repo = MagicMock()
    repo.filter_by.return_value = []
    handler = GetPurchaseOrderItemsByPOQueryHandler(repo, MagicMock())

    result = handler.handle(GetPurchaseOrderItemsByPOQuery(purchase_order_id=99))

    assert result == []


# ---------------------------------------------------------------------------
# GetReceiptsByPurchaseOrderQueryHandler
# ---------------------------------------------------------------------------


def test_get_receipts_by_po():
    receipt = _make_receipt()
    repo = MagicMock()
    repo.filter_by.return_value = [receipt]
    handler = GetReceiptsByPurchaseOrderQueryHandler(repo)

    result = handler.handle(GetReceiptsByPurchaseOrderQuery(purchase_order_id=1))

    repo.filter_by.assert_called_once_with(purchase_order_id=1)
    assert len(result) == 1


def test_get_receipts_by_po_empty():
    repo = MagicMock()
    repo.filter_by.return_value = []
    handler = GetReceiptsByPurchaseOrderQueryHandler(repo)

    result = handler.handle(GetReceiptsByPurchaseOrderQuery(purchase_order_id=99))

    assert result == []
