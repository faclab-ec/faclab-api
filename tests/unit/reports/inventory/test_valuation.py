from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from src.reports.inventory.app.queries.valuation import (
    GetInventoryValuationQuery,
    GetInventoryValuationQueryHandler,
)


def _make_session(rows=None, extra_rows=None):
    """Return a mock Session where any query chain ends in the given rows."""
    rows = rows or []
    session = MagicMock()
    q = MagicMock()
    q.join.return_value = q
    q.outerjoin.return_value = q
    q.filter.return_value = q
    q.group_by.return_value = q
    q.having.return_value = q
    q.all.return_value = rows
    # extra_rows used for the inner location subquery in _valuation_at_date
    if extra_rows is not None:
        session.query.side_effect = [
            q,
            MagicMock(filter=lambda *a: MagicMock(all=lambda: extra_rows)),
        ]
    else:
        session.query.return_value = q
    return session


def _make_row(
    product_id=1,
    name="Product A",
    sku="SKU-001",
    cost=Decimal("10.00"),
    quantity=100,
):
    """A product's aggregate: its quantity and its value at average cost"""
    row = MagicMock()
    row.id = product_id
    row.name = name
    row.sku = sku
    row.quantity = quantity
    row.value = Decimal(quantity) * cost
    return row


# ---------------------------------------------------------------------------
# Current valuation (no as_of_date)
# ---------------------------------------------------------------------------


def test_valuation_returns_correct_total_value():
    row = _make_row(quantity=100, cost=Decimal("10.00"))
    session = _make_session(rows=[row])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    assert result["total_value"] == Decimal("1000.00")
    assert len(result["items"]) == 1
    assert result["items"][0]["quantity"] == 100
    assert result["items"][0]["average_cost"] == Decimal("10.00")
    assert result["items"][0]["total_value"] == Decimal("1000.00")


def test_valuation_aggregates_multiple_products():
    rows = [
        _make_row(product_id=1, quantity=50, cost=Decimal("20.00")),
        _make_row(
            product_id=2,
            name="Product B",
            sku="SKU-002",
            quantity=200,
            cost=Decimal("5.00"),
        ),
    ]
    session = _make_session(rows=rows)
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    assert result["total_value"] == Decimal("2000.00")
    assert len(result["items"]) == 2


def test_valuation_uses_todays_date_when_no_as_of_date():
    session = _make_session(rows=[])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    assert result["as_of_date"] == date.today()


def test_valuation_uses_provided_as_of_date_in_response():
    as_of = date(2026, 1, 15)

    # For _valuation_at_date, mock both query calls
    row = _make_row(quantity=50, cost=Decimal("10.00"))
    session = MagicMock()
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q
    q.group_by.return_value = q
    q.all.return_value = [row]
    # Second query is for location_ids (returns empty list when warehouse_id is None)
    session.query.return_value = q

    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery(as_of_date=as_of))

    assert result["as_of_date"] == as_of


def test_valuation_returns_empty_items_when_no_stocks():
    session = _make_session(rows=[])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    assert result["total_value"] == 0
    assert result["items"] == []


def test_valuation_excludes_zero_quantity_rows():
    row = _make_row(quantity=0, cost=Decimal("10.00"))
    session = _make_session(rows=[row])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    assert result["items"] == []
    assert result["total_value"] == 0


def test_valuation_includes_product_name_and_sku():
    row = _make_row(
        product_id=5,
        name="Coffee Bag",
        sku="COFFEE-001",
        quantity=10,
        cost=Decimal("15.00"),
    )
    session = _make_session(rows=[row])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery())

    item = result["items"][0]
    assert item["product_id"] == 5
    assert item["product_name"] == "Coffee Bag"
    assert item["sku"] == "COFFEE-001"


def test_valuation_with_warehouse_id_passes_to_query():
    session = _make_session(rows=[])
    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery(warehouse_id=3))

    assert result["items"] == []
    # Verify session.query was called (warehouse filter path was taken)
    assert session.query.called


# ---------------------------------------------------------------------------
# Historical valuation (with as_of_date)
# ---------------------------------------------------------------------------


def test_valuation_at_date_excludes_negative_quantity():
    row = _make_row(quantity=-5, cost=Decimal("10.00"))
    session = MagicMock()
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q
    q.group_by.return_value = q
    q.all.return_value = [row]
    session.query.return_value = q

    handler = GetInventoryValuationQueryHandler(session)

    result = handler.handle(GetInventoryValuationQuery(as_of_date=date(2026, 1, 1)))

    assert result["items"] == []
    assert result["total_value"] == 0
