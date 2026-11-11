"""States, validity and totals of a quote (S5.4)"""

from datetime import timedelta
from decimal import Decimal

import pytest

from src.quotes.domain.entities import Quote, QuoteStatus
from src.quotes.domain.exceptions import (
    InvalidQuoteStatusError,
    QuoteAlreadyConvertedError,
    QuoteExpiredError,
    QuoteWithoutItemsError,
)
from src.sales.domain.entities import Sale, SaleItem
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.tax import TaxCode
from tests.unit.quotes.fakes import NEXT_WEEK, TODAY, draft, line

YESTERDAY = TODAY - timedelta(days=1)


def test_a_new_quote_is_a_draft_issued_today():
    quote = Quote.draft(branch_id=1, valid_until=NEXT_WEEK, today=TODAY)

    assert (quote.status, quote.issue_date, quote.number) == (
        QuoteStatus.DRAFT,
        TODAY,
        None,
    )


def test_a_quote_is_valid_until_today_or_later():
    Quote.draft(branch_id=1, valid_until=TODAY, today=TODAY)

    with pytest.raises(InvalidValueError):
        Quote.draft(branch_id=1, valid_until=YESTERDAY, today=TODAY)


def test_sending_and_accepting_need_items_and_validity():
    quote = draft()
    with pytest.raises(QuoteWithoutItemsError):
        quote.send(0, TODAY)

    quote.send(1, TODAY)
    assert quote.status == QuoteStatus.SENT
    assert quote.sent_at is not None

    quote.accept(1, TODAY)
    assert quote.status == QuoteStatus.ACCEPTED
    with pytest.raises(InvalidQuoteStatusError):
        quote.send(1, TODAY)

    with pytest.raises(QuoteExpiredError):
        draft(valid_until=YESTERDAY, issue_date=YESTERDAY).accept(1, TODAY)


def test_only_a_draft_is_edited():
    quote = draft(status=QuoteStatus.SENT)

    with pytest.raises(InvalidQuoteStatusError):
        quote.change(customer_id=None, valid_until=NEXT_WEEK, notes=None, today=TODAY)


def test_emailing_a_draft_sends_it_and_a_sent_one_goes_again():
    quote = draft()
    quote.mark_emailed(1, TODAY)
    assert quote.status == QuoteStatus.SENT

    quote.accept(1, TODAY)
    quote.mark_emailed(1, TODAY)
    assert quote.status == QuoteStatus.ACCEPTED

    with pytest.raises(InvalidQuoteStatusError):
        draft(status=QuoteStatus.CONVERTED).mark_emailed(1, TODAY)


@pytest.mark.parametrize(
    "status", [QuoteStatus.DRAFT, QuoteStatus.SENT, QuoteStatus.ACCEPTED]
)
def test_an_open_quote_past_its_date_is_expired_before_the_task_marks_it(status):
    quote = draft(status=status, valid_until=YESTERDAY, issue_date=YESTERDAY)

    assert quote.is_expired(TODAY)
    with pytest.raises(QuoteExpiredError):
        quote.ensure_convertible(TODAY)
    assert quote.expire(TODAY)
    assert quote.status == QuoteStatus.EXPIRED


def test_a_quote_in_force_its_last_day_is_not_expired():
    quote = draft(valid_until=TODAY)

    assert not quote.is_expired(TODAY)
    assert not quote.expire(TODAY)
    quote.ensure_convertible(TODAY)


def test_an_expired_quote_is_not_converted_until_it_is_renewed():
    quote = draft(
        status=QuoteStatus.EXPIRED, valid_until=YESTERDAY, issue_date=YESTERDAY
    )
    with pytest.raises(QuoteExpiredError):
        quote.convert(TODAY)

    quote.renew(NEXT_WEEK, TODAY)

    assert (quote.status, quote.issue_date, quote.valid_until) == (
        QuoteStatus.DRAFT,
        TODAY,
        NEXT_WEEK,
    )
    quote.convert(TODAY)
    assert quote.status == QuoteStatus.CONVERTED
    assert quote.converted_at is not None


def test_only_an_expired_quote_is_renewed():
    with pytest.raises(InvalidQuoteStatusError):
        draft().renew(NEXT_WEEK, TODAY)
    with pytest.raises(InvalidValueError):
        draft(
            status=QuoteStatus.EXPIRED, valid_until=YESTERDAY, issue_date=YESTERDAY
        ).renew(YESTERDAY, TODAY)


def test_a_converted_quote_is_not_converted_again():
    with pytest.raises(QuoteAlreadyConvertedError):
        draft(status=QuoteStatus.CONVERTED).convert(TODAY)


def test_its_totals_are_those_of_a_sale_with_the_same_lines():
    lines = [
        line(
            id=1, quantity=Decimal(3), unit_price=Decimal("9.50"), discount=Decimal(10)
        ),
        line(
            id=2,
            product_id=200,
            quantity=Decimal("2.5"),
            unit_price=Decimal("4.333333"),
            tax_code=TaxCode.VAT_0,
        ),
        line(id=3, quantity=Decimal(1), unit_price=Decimal("0.07")),
    ]
    quote = draft()
    quote.recalculate_totals(lines)

    sale = Sale()
    sale_items = []
    for item in lines:
        sale_item = SaleItem(
            sale_id=1,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount=item.discount,
            tax_code=item.tax_code,
        )
        sale_item.recalculate_tax()
        sale_items.append(sale_item)
    sale.recalculate_totals(sale_items)

    assert (quote.subtotal, quote.tax, quote.total) == (
        sale.subtotal,
        sale.tax,
        sale.total,
    )
    assert quote.total == quote.subtotal + quote.tax
