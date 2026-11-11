"""What the POS sees of a quote before charging it: whether it expired, today's
price of each line and the stock at the terminal (S5.4)"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.inventory.stock.domain.entities import Stock
from src.pricing.domain.entities import PriceList, PriceListItem
from src.quotes.app.queries.pos import GetPosQuoteQuery, GetPosQuoteQueryHandler
from src.shared.domain.exceptions import NotFoundError
from tests.prices import price_resolver
from tests.unit.pos.terminals import AT_TERMINAL, LOCATION_ID, terminal_resolver
from tests.unit.quotes.fakes import (
    TODAY,
    InMemoryQuoteItems,
    InMemoryQuotes,
    QuotePresentations,
    catalog,
    draft,
    line,
    views,
)

GENERAL = PriceList(id=1, name="General", is_default=True)


def _handler(quote, items, stock_rows, resolver=None):
    products, presentation_repo = catalog()
    stock = Mock()
    stock.first.side_effect = lambda product_id, location_id: next(
        (
            s
            for s in stock_rows
            if s.product_id == product_id and s.location_id == location_id
        ),
        None,
    )
    item_repo = InMemoryQuoteItems(*items)
    return GetPosQuoteQueryHandler(
        InMemoryQuotes(quote),
        item_repo,
        terminal_resolver(),
        products,
        presentation_repo,
        QuotePresentations(),
        resolver or price_resolver(),
        stock,
        views(items=item_repo),
    )


def test_it_shows_todays_price_and_the_stock_of_the_terminal():
    # Quoted at 9.20; today the product sells at 9.50
    items = [
        line(id=1, quantity=Decimal(4), unit_price=Decimal("9.20")),
        line(id=2, quantity=Decimal(3), unit_price=Decimal("9.50")),
    ]
    stock = [
        Stock(product_id=100, quantity=Decimal(10), location_id=LOCATION_ID),
        Stock(product_id=100, quantity=Decimal(500), location_id=99),
    ]

    result = _handler(draft(), items, stock).handle(
        GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL)
    )

    first, second = result["items"]
    assert (first["list_price"], first["price_changed"]) == (Decimal("9.50"), True)
    assert second["price_changed"] is False
    # Both lines take 7 of the 10 at the terminal's location
    assert (first["available_quantity"], first["enough_stock"]) == (Decimal(10), True)
    assert result["expired"] is False


def test_the_lines_of_a_product_need_its_stock_together():
    items = [line(id=1, quantity=Decimal(6)), line(id=2, quantity=Decimal(6))]
    stock = [Stock(product_id=100, quantity=Decimal(10), location_id=LOCATION_ID)]

    result = _handler(draft(), items, stock).handle(
        GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL)
    )

    assert [i["enough_stock"] for i in result["items"]] == [False, False]


def test_without_a_stock_row_there_is_none():
    result = _handler(draft(), [line()], []).handle(
        GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL)
    )

    assert result["items"][0]["available_quantity"] == 0
    assert result["items"][0]["enough_stock"] is False


def test_the_list_of_its_customer_prices_it():
    resolver = price_resolver(
        [GENERAL, PriceList(id=2, name="Mayorista")],
        [
            PriceListItem(
                price_list_id=2, product_id=100, presentation_id=10, price=Decimal("8")
            )
        ],
        customer_lists={6: 2},
    )

    result = _handler(
        draft(customer_id=6), [line(unit_price=Decimal("8"))], [], resolver
    ).handle(GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL))

    [item] = result["items"]
    assert (item["list_price"], item["price_list_name"]) == (Decimal("8"), "Mayorista")
    assert item["price_changed"] is False


def test_an_expired_quote_says_so():
    past = TODAY - timedelta(days=2)

    result = _handler(draft(valid_until=past, issue_date=past), [line()], []).handle(
        GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL)
    )

    assert result["expired"] is True


def test_a_quote_of_another_branch_is_not_found():
    with pytest.raises(NotFoundError):
        _handler(draft(branch_id=2), [line()], []).handle(
            GetPosQuoteQuery(quote_id=1, request=AT_TERMINAL)
        )
