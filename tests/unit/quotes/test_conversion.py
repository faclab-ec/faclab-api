"""A quote charged at the POS: in force, of the terminal's branch, for the same
customer and with its same items (S5.4)"""

from datetime import timedelta
from decimal import Decimal

import pytest

from src.quotes.app.conversion import QuoteConversion
from src.quotes.domain.entities import QuoteStatus
from src.quotes.domain.exceptions import (
    QuoteAlreadyConvertedError,
    QuoteCustomerChangedError,
    QuoteExpiredError,
    QuoteItemsChangedError,
    QuoteOutsideBranchError,
)
from src.sales.domain.entities import SaleItem
from src.shared.domain.exceptions import NotFoundError
from tests.unit.quotes.fakes import (
    CEMENT_BASE,
    TODAY,
    InMemoryQuoteItems,
    InMemoryQuotes,
    draft,
    line,
)


def _conversion(quote=None, *items):
    quotes = InMemoryQuotes(*([quote] if quote else []))
    return QuoteConversion(quotes, InMemoryQuoteItems(*items)), quotes


def _sold(product_id=100, presentation_id=CEMENT_BASE.id, quantity="2", discount="0"):
    return SaleItem(
        sale_id=1,
        product_id=product_id,
        presentation_id=presentation_id,
        quantity=Decimal(quantity),
        unit_price=Decimal("9.50"),
        discount=Decimal(discount),
    )


def test_taking_a_quote_locks_it():
    conversion, quotes = _conversion(draft())

    quote = conversion.take(1, branch_id=1, customer_id=5)

    assert quote.id == 1
    assert quotes.locked == [1]


def test_a_quote_of_another_branch_is_charged_at_its_own():
    conversion, _ = _conversion(draft(branch_id=2))

    with pytest.raises(QuoteOutsideBranchError):
        conversion.take(1, branch_id=1, customer_id=5)


def test_an_expired_quote_is_not_charged():
    past = TODAY - timedelta(days=1)
    conversion, _ = _conversion(draft(valid_until=past, issue_date=past))

    with pytest.raises(QuoteExpiredError):
        conversion.take(1, branch_id=1, customer_id=5)


def test_a_converted_quote_is_not_charged_again():
    conversion, _ = _conversion(draft(status=QuoteStatus.CONVERTED))

    with pytest.raises(QuoteAlreadyConvertedError):
        conversion.take(1, branch_id=1, customer_id=5)


def test_the_sale_is_for_the_quotes_customer():
    conversion, _ = _conversion(draft(customer_id=5))

    with pytest.raises(QuoteCustomerChangedError):
        conversion.take(1, branch_id=1, customer_id=None)


def test_a_missing_quote_is_not_found():
    conversion, _ = _conversion()

    with pytest.raises(NotFoundError):
        conversion.take(1, branch_id=1, customer_id=5)


def test_the_sale_carries_its_same_items_in_any_order():
    quote = draft()
    conversion, _ = _conversion(
        quote,
        line(id=1, quantity=Decimal(2)),
        line(id=2, product_id=200, presentation_id=21, quantity=Decimal(3)),
    )

    conversion.ensure_items(
        quote,
        [
            _sold(product_id=200, presentation_id=21, quantity="3.000000"),
            _sold(quantity="2"),
        ],
    )


@pytest.mark.parametrize(
    "sold",
    [
        [_sold(quantity="3")],
        [_sold(discount="5")],
        [_sold(presentation_id=None)],
        [_sold(), _sold()],
        [],
    ],
)
def test_other_items_are_not_the_quote(sold):
    quote = draft()
    conversion, _ = _conversion(quote, line(quantity=Decimal(2)))

    with pytest.raises(QuoteItemsChangedError):
        conversion.ensure_items(quote, sold)


def test_converting_closes_the_quote():
    quote = draft(status=QuoteStatus.ACCEPTED)
    conversion, quotes = _conversion(quote)

    conversion.convert(quote)

    assert quotes.rows[1].status == QuoteStatus.CONVERTED
    assert quotes.rows[1].converted_at is not None
