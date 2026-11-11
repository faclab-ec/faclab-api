"""Quotes: created and numbered per branch, priced by the lists of their
customer, renewed with today's prices and sent by email (S5.4)"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from src.auth.domain.exceptions import BranchAccessDeniedError
from src.customers.domain.entities import Customer
from src.organization.domain.exceptions import BranchInactiveError
from src.organization.domain.numbering import DocumentType
from src.pricing.domain.entities import PriceList, PriceListItem
from src.quotes.app.commands.actions import (
    AcceptQuoteCommand,
    AcceptQuoteCommandHandler,
    EmailQuoteCommand,
    EmailQuoteCommandHandler,
    RenewQuoteCommand,
    RenewQuoteCommandHandler,
    SendQuoteCommand,
    SendQuoteCommandHandler,
)
from src.quotes.app.commands.items import (
    AddQuoteItemCommand,
    AddQuoteItemCommandHandler,
    RemoveQuoteItemCommand,
    RemoveQuoteItemCommandHandler,
    UpdateQuoteItemCommand,
    UpdateQuoteItemCommandHandler,
)
from src.quotes.app.commands.quotes import (
    CreateQuoteCommand,
    CreateQuoteCommandHandler,
    DeleteQuoteCommand,
    DeleteQuoteCommandHandler,
    UpdateQuoteCommand,
    UpdateQuoteCommandHandler,
)
from src.quotes.app.document import QuoteDocument
from src.quotes.app.queries.quotes import GetQuoteQuery, GetQuoteQueryHandler
from src.quotes.domain.entities import QuoteStatus
from src.quotes.domain.exceptions import (
    InvalidQuoteStatusError,
    QuoteEmailRequiredError,
    QuoteLineWithoutPriceError,
    QuoteWithoutItemsError,
)
from src.shared.app.mail import EmailDeliveryFailedError, OutgoingMail
from src.shared.domain.exceptions import InvalidValueError, NotFoundError
from src.shared.domain.quantity import QuantityPrecisionError
from tests.prices import price_resolver
from tests.quantities import FakeProductQuantities
from tests.unit.quotes.fakes import (
    CEMENT,
    NEXT_WEEK,
    SCREW_BOX,
    TODAY,
    InMemoryQuoteItems,
    InMemoryQuotes,
    catalog,
    draft,
    line,
    pricing,
    views,
)

WHOLESALE = PriceList(id=1, name="Mayorista")
# The wholesale list: cement at 8.90, 8.00 from 10 bags
WHOLESALE_PRICES = [
    PriceListItem(
        id=1, price_list_id=1, product_id=100, presentation_id=10, price=Decimal("8.90")
    ),
    PriceListItem(
        id=2,
        price_list_id=1,
        product_id=100,
        presentation_id=10,
        price=Decimal("8.00"),
        min_quantity=Decimal(10),
    ),
]
WHOLESALER = Customer(id=6, name="Constructora Andes", tax_id="1790012345001")
RETAIL = Customer(id=5, name="Ana Pérez", tax_id="0102030405", email="ana@example.com")


def _wholesale_pricing():
    return pricing(price_resolver([WHOLESALE], WHOLESALE_PRICES, customer_lists={6: 1}))


def _branches(active=True):
    branches = Mock()
    branches.get_by_id.side_effect = lambda i: (
        SimpleNamespace(id=i, is_active=active) if i in (1, 2) else None
    )
    return branches


def _customers(*customers):
    repo = Mock()
    by_id = {c.id: c for c in customers}
    repo.get_by_id.side_effect = by_id.get
    return repo


def _create_handler(quotes=None, branches=None, numbering=None):
    if numbering is None:
        numbering = MagicMock()
        numbering.next.return_value = "COT-001-000007"
    return CreateQuoteCommandHandler(
        quotes or InMemoryQuotes(),
        branches or _branches(),
        _customers(RETAIL, WHOLESALER),
        numbering,
        views(),
    )


def _add_handler(quotes, items, prices=None):
    products, _ = catalog()
    return AddQuoteItemCommandHandler(
        quotes,
        items,
        products,
        prices.presentations if prices else pricing().presentations,
        FakeProductQuantities(),
        prices or pricing(),
        views(),
    )


# Creating


def test_a_new_quote_is_a_draft_numbered_in_its_branch():
    numbering = MagicMock()
    numbering.next.return_value = "COT-001-000007"
    quotes = InMemoryQuotes()

    result = _create_handler(quotes, numbering=numbering).handle(
        CreateQuoteCommand(
            branch_id=1, valid_until=NEXT_WEEK, customer_id=5, created_by="Ana"
        )
    )

    numbering.next.assert_called_once_with(1, DocumentType.QUOTE)
    assert result["number"] == "COT-001-000007"
    assert result["status"] == QuoteStatus.DRAFT
    assert (result["issue_date"], result["created_by"]) == (TODAY, "Ana")
    assert result["items"] == []
    assert quotes.rows[result["id"]].number == "COT-001-000007"


def test_a_quote_for_the_final_consumer_has_no_customer():
    result = _create_handler().handle(
        CreateQuoteCommand(branch_id=1, valid_until=TODAY)
    )

    assert result["customer_id"] is None
    assert result["customer_name"] is None


def test_a_quote_is_made_in_a_branch_the_user_may_enter():
    with pytest.raises(BranchAccessDeniedError):
        _create_handler().handle(
            CreateQuoteCommand(
                branch_id=2, valid_until=NEXT_WEEK, branch_ids=frozenset({1})
            )
        )


def test_an_inactive_or_missing_branch_issues_no_quote():
    with pytest.raises(BranchInactiveError):
        _create_handler(branches=_branches(active=False)).handle(
            CreateQuoteCommand(branch_id=1, valid_until=NEXT_WEEK)
        )
    with pytest.raises(NotFoundError):
        _create_handler().handle(CreateQuoteCommand(branch_id=9, valid_until=NEXT_WEEK))


def test_a_past_validity_spends_no_number():
    numbering = MagicMock()

    with pytest.raises(InvalidValueError):
        _create_handler(numbering=numbering).handle(
            CreateQuoteCommand(branch_id=1, valid_until=TODAY - timedelta(days=1))
        )
    numbering.next.assert_not_called()


def test_an_unknown_customer_is_not_found():
    with pytest.raises(NotFoundError):
        _create_handler().handle(
            CreateQuoteCommand(branch_id=1, valid_until=NEXT_WEEK, customer_id=99)
        )


# Items


def test_an_item_takes_the_price_of_its_customer_list_and_tier():
    quotes, items = InMemoryQuotes(draft(customer_id=6)), InMemoryQuoteItems()
    handler = _add_handler(quotes, items, _wholesale_pricing())

    handler.handle(AddQuoteItemCommand(quote_id=1, product_id=100, quantity=Decimal(2)))
    result = handler.handle(
        AddQuoteItemCommand(quote_id=1, product_id=100, quantity=Decimal(12))
    )

    assert [i["unit_price"] for i in result["items"]] == [
        Decimal("8.90"),
        Decimal("8.00"),
    ]
    # 2 × 8.90 + 12 × 8.00 = 113.80, plus 15% VAT
    assert (result["subtotal"], result["tax"], result["total"]) == (
        Decimal("113.80"),
        Decimal("17.07"),
        Decimal("130.87"),
    )
    assert quotes.locked == [1, 1]


def test_an_item_in_a_presentation_takes_its_price_and_factor():
    quotes, items = InMemoryQuotes(draft()), InMemoryQuoteItems()

    result = _add_handler(quotes, items).handle(
        AddQuoteItemCommand(
            quote_id=1, product_id=200, presentation_id=21, quantity=Decimal(3)
        )
    )

    [item] = result["items"]
    # Without its own price, the box is 100 × the screw's
    assert item["unit_price"] == SCREW_BOX.effective_sale_price(Decimal("0.05"))
    assert (item["unit_factor"], item["base_quantity"]) == (Decimal(100), Decimal(300))
    assert item["presentation_name"] == "Caja x100"


def test_a_product_without_any_price_is_not_quoted():
    quotes, items = InMemoryQuotes(draft()), InMemoryQuoteItems()
    products, _ = catalog()
    products.get_by_id.side_effect = lambda i: replace(CEMENT, sale_price=None)
    prices = pricing()
    handler = AddQuoteItemCommandHandler(
        quotes,
        items,
        products,
        prices.presentations,
        FakeProductQuantities(),
        prices,
        views(),
    )

    with pytest.raises(QuoteLineWithoutPriceError):
        handler.handle(
            AddQuoteItemCommand(quote_id=1, product_id=100, quantity=Decimal(1))
        )


def test_a_quantity_takes_the_decimals_of_its_unit():
    quotes, items = InMemoryQuotes(draft()), InMemoryQuoteItems()
    products, _ = catalog()
    prices = pricing()
    handler = AddQuoteItemCommandHandler(
        quotes,
        items,
        products,
        prices.presentations,
        FakeProductQuantities({100: 0}),
        prices,
        views(),
    )

    with pytest.raises(QuantityPrecisionError):
        handler.handle(
            AddQuoteItemCommand(quote_id=1, product_id=100, quantity=Decimal("1.5"))
        )


def test_only_a_draft_takes_items():
    quotes = InMemoryQuotes(draft(status=QuoteStatus.SENT))

    with pytest.raises(InvalidQuoteStatusError):
        _add_handler(quotes, InMemoryQuoteItems()).handle(
            AddQuoteItemCommand(quote_id=1, product_id=100, quantity=Decimal(1))
        )


def test_another_quantity_takes_the_price_of_its_tier():
    quotes = InMemoryQuotes(draft(customer_id=6))
    items = InMemoryQuoteItems(line(unit_price=Decimal("8.90")))

    result = UpdateQuoteItemCommandHandler(
        quotes, items, FakeProductQuantities(), _wholesale_pricing(), views()
    ).handle(
        UpdateQuoteItemCommand(
            quote_id=1, item_id=1, quantity=Decimal(10), discount=Decimal(5)
        )
    )

    [item] = result["items"]
    assert (item["unit_price"], item["discount"]) == (Decimal("8.00"), Decimal(5))
    # 10 × 8.00 − 5%
    assert result["subtotal"] == Decimal("76.00")


def test_an_item_of_another_quote_is_not_found():
    quotes = InMemoryQuotes(draft(), draft(id=2))
    items = InMemoryQuoteItems(line(quote_id=2))

    with pytest.raises(NotFoundError):
        RemoveQuoteItemCommandHandler(quotes, items, views()).handle(
            RemoveQuoteItemCommand(quote_id=1, item_id=1)
        )


def test_removing_an_item_recomputes_the_totals():
    quotes = InMemoryQuotes(draft(subtotal=Decimal(19)))
    items = InMemoryQuoteItems(line())

    result = RemoveQuoteItemCommandHandler(quotes, items, views()).handle(
        RemoveQuoteItemCommand(quote_id=1, item_id=1)
    )

    assert (result["items"], result["total"]) == ([], Decimal(0))


# Editing


def test_another_customer_prices_the_lines_with_its_lists():
    quotes = InMemoryQuotes(draft(customer_id=5))
    items = InMemoryQuoteItems(line(quantity=Decimal(12)))

    result = UpdateQuoteCommandHandler(
        quotes, items, _customers(RETAIL, WHOLESALER), _wholesale_pricing(), views()
    ).handle(
        UpdateQuoteCommand(
            quote_id=1, customer_id=6, valid_until=NEXT_WEEK, notes="Obra Calderón"
        )
    )

    assert result["items"][0]["unit_price"] == Decimal("8.00")
    assert items.rows[1].unit_price == Decimal("8.00")
    assert (result["customer_id"], result["notes"]) == (6, "Obra Calderón")


def test_a_quote_outside_the_users_branches_is_not_found():
    quotes = InMemoryQuotes(draft(branch_id=2))

    with pytest.raises(NotFoundError):
        DeleteQuoteCommandHandler(quotes).handle(
            DeleteQuoteCommand(quote_id=1, branch_ids=frozenset({1}))
        )
    with pytest.raises(NotFoundError):
        GetQuoteQueryHandler(quotes, views()).handle(
            GetQuoteQuery(quote_id=1, branch_ids=frozenset({1}))
        )


def test_only_a_draft_is_deleted():
    quotes = InMemoryQuotes(draft(status=QuoteStatus.SENT))

    with pytest.raises(InvalidQuoteStatusError):
        DeleteQuoteCommandHandler(quotes).handle(DeleteQuoteCommand(quote_id=1))

    quotes = InMemoryQuotes(draft())
    DeleteQuoteCommandHandler(quotes).handle(DeleteQuoteCommand(quote_id=1))
    assert quotes.rows == {}


# Actions


def test_sending_or_accepting_needs_items():
    quotes = InMemoryQuotes(draft())

    with pytest.raises(QuoteWithoutItemsError):
        SendQuoteCommandHandler(quotes, InMemoryQuoteItems(), views()).handle(
            SendQuoteCommand(quote_id=1)
        )

    items = InMemoryQuoteItems(line())
    SendQuoteCommandHandler(quotes, items, views()).handle(SendQuoteCommand(quote_id=1))
    result = AcceptQuoteCommandHandler(quotes, items, views()).handle(
        AcceptQuoteCommand(quote_id=1)
    )
    assert result["status"] == QuoteStatus.ACCEPTED


def test_a_renewed_quote_takes_todays_prices_and_is_a_draft_again():
    expired = draft(
        customer_id=6,
        status=QuoteStatus.EXPIRED,
        issue_date=TODAY - timedelta(days=30),
        valid_until=TODAY - timedelta(days=15),
    )
    quotes = InMemoryQuotes(expired)
    # Quoted at 9.20 a month ago; the wholesale list now says 8.90
    items = InMemoryQuoteItems(line(unit_price=Decimal("9.20")))

    result = RenewQuoteCommandHandler(
        quotes, items, _wholesale_pricing(), views()
    ).handle(RenewQuoteCommand(quote_id=1, valid_until=NEXT_WEEK))

    assert (result["status"], result["issue_date"], result["valid_until"]) == (
        QuoteStatus.DRAFT,
        TODAY,
        NEXT_WEEK,
    )
    assert result["items"][0]["unit_price"] == Decimal("8.90")
    assert result["subtotal"] == Decimal("17.80")


# Email


class RecordingMailer:
    def __init__(self, error: Exception | None = None):
        self.sent: list[OutgoingMail] = []
        self.error = error

    def send(self, mail: OutgoingMail) -> None:
        if self.error:
            raise self.error
        self.sent.append(mail)


def _document(**overrides: Any) -> QuoteDocument:
    values: dict[str, Any] = {
        "number": "COT-001-000001",
        "issue_date": TODAY,
        "valid_until": NEXT_WEEK,
        "issuer_name": "Ferretería El Clavo S.A.",
        "issuer_trade_name": "El Clavo",
        "issuer_ruc": "1790012345001",
        "branch_name": "Matriz",
        "establishment_code": "001",
        "lines": (),
        "taxes": (),
        "subtotal": Decimal("19.00"),
        "tax": Decimal("2.85"),
        "total": Decimal("21.85"),
        "customer_name": "Ana Pérez",
        "customer_email": "ana@example.com",
    }
    return QuoteDocument(**{**values, **overrides})


def _email_handler(quotes, mailer, document=None):
    documents = Mock()
    document = document or _document()
    documents.pdf.return_value = (document, b"%PDF-1.4 quote")
    return EmailQuoteCommandHandler(
        quotes, InMemoryQuoteItems(line()), documents, mailer, views()
    )


def test_a_quote_goes_by_email_to_its_customer_with_its_pdf():
    quotes, mailer = InMemoryQuotes(draft()), RecordingMailer()

    result = _email_handler(quotes, mailer).handle(EmailQuoteCommand(quote_id=1))

    [mail] = mailer.sent
    assert mail.to == "ana@example.com"
    assert mail.subject == "Cotización COT-001-000001 · El Clavo"
    assert mail.sender_name == "El Clavo"
    assert "$21.85" in mail.text
    [attachment] = mail.attachments
    assert attachment.filename == "cotizacion-COT-001-000001.pdf"
    assert attachment.content.startswith(b"%PDF")
    assert result["status"] == QuoteStatus.SENT


def test_a_quote_goes_to_the_address_given():
    mailer = RecordingMailer()

    _email_handler(InMemoryQuotes(draft()), mailer).handle(
        EmailQuoteCommand(quote_id=1, to="obra@example.com")
    )

    assert mailer.sent[0].to == "obra@example.com"


def test_without_an_address_nothing_is_sent():
    mailer = RecordingMailer()
    handler = _email_handler(
        InMemoryQuotes(draft()), mailer, _document(customer_email=None)
    )

    with pytest.raises(QuoteEmailRequiredError):
        handler.handle(EmailQuoteCommand(quote_id=1))
    with pytest.raises(InvalidValueError):
        handler.handle(EmailQuoteCommand(quote_id=1, to="not an email"))
    assert mailer.sent == []


def test_a_refused_email_fails_the_request():
    mailer = RecordingMailer(EmailDeliveryFailedError("SMTPRecipientsRefused"))

    with pytest.raises(EmailDeliveryFailedError):
        _email_handler(InMemoryQuotes(draft()), mailer).handle(
            EmailQuoteCommand(quote_id=1)
        )
