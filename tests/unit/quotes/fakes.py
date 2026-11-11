"""In-memory quotes and items, and the catalog around them, for the quote tests"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from src.catalog.product.domain.entities import Product, ProductPresentation
from src.quotes.app.pricing import QuotePricing
from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.app.views import QuoteViews
from src.quotes.domain.entities import Quote, QuoteItem
from src.shared.domain.tax import TaxCode
from tests.presentations import FakeProductPresentations
from tests.prices import price_resolver

TODAY = date.today()
NEXT_WEEK = TODAY + timedelta(days=7)
BRANCH_ID = 1

CEMENT = Product(id=100, name="Cemento", sku="FERR-003", sale_price=Decimal("9.50"))
SCREW = Product(
    id=200,
    name="Tornillo 1/2",
    sku="FERR-010",
    sale_price=Decimal("0.05"),
    tax_code=TaxCode.VAT_0,
)
CEMENT_BASE = ProductPresentation(id=10, product_id=100, name="Saco", is_base=True)
SCREW_BOX = ProductPresentation(
    id=21, product_id=200, name="Caja x100", factor=Decimal(100)
)
PRODUCTS = {p.id: p for p in (CEMENT, SCREW)}
PRESENTATIONS = {p.id: p for p in (CEMENT_BASE, SCREW_BOX)}


class QuotePresentations(FakeProductPresentations):
    """The cement sells in its saved base presentation (10), the screw in an
    unsaved one or in its box"""

    def __init__(self):
        super().__init__(PRESENTATIONS.values())

    def resolve(self, product, presentation_id):
        if presentation_id is None and product.id == CEMENT.id:
            return CEMENT_BASE
        return super().resolve(product, presentation_id)


class InMemoryQuotes(QuoteRepository):
    def __init__(self, *quotes: Quote):
        self.rows: dict[int, Quote] = {q.require_id(): replace(q) for q in quotes}
        self.locked: list[int] = []

    def create(self, entity: Quote) -> Quote:
        entity = replace(entity, id=max(self.rows, default=0) + 1)
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def update(self, entity: Quote) -> Quote:
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def delete(self, id: int) -> None:
        del self.rows[id]

    def get_by_id(self, id: int) -> Quote | None:
        row = self.rows.get(id)
        return replace(row) if row else None

    def first_for_update(self, **kwargs) -> Quote | None:
        self.locked.append(kwargs["id"])
        return self.get_by_id(kwargs["id"])

    def page(self, where, limit, offset) -> dict:
        items = list(self.rows.values())
        return {"total": len(items), "limit": limit, "offset": offset, "items": items}

    get_all = get_by_ids = first = filter_by = count_by = Mock()
    filter_by_spec = count_by_spec = paginate = paginate_by_spec = Mock()


class InMemoryQuoteItems(QuoteItemRepository):
    def __init__(self, *items: QuoteItem):
        self.rows: dict[int, QuoteItem] = {i.require_id(): replace(i) for i in items}

    def create(self, entity: QuoteItem) -> QuoteItem:
        entity = replace(entity, id=max(self.rows, default=0) + 1)
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def update(self, entity: QuoteItem) -> QuoteItem:
        self.rows[entity.require_id()] = replace(entity)
        return replace(entity)

    def delete(self, id: int) -> None:
        del self.rows[id]

    def get_by_id(self, id: int) -> QuoteItem | None:
        row = self.rows.get(id)
        return replace(row) if row else None

    def for_quote(self, quote_id: int) -> list[QuoteItem]:
        return [
            replace(i) for _, i in sorted(self.rows.items()) if i.quote_id == quote_id
        ]

    def for_quotes(self, quote_ids) -> list[QuoteItem]:
        return [replace(i) for i in self.rows.values() if i.quote_id in set(quote_ids)]

    get_all = get_by_ids = first = filter_by = count_by = Mock()
    filter_by_spec = count_by_spec = paginate = paginate_by_spec = Mock()


def draft(**overrides: Any) -> Quote:
    values: dict[str, Any] = {
        "id": 1,
        "branch_id": BRANCH_ID,
        "number": "COT-001-000001",
        "valid_until": NEXT_WEEK,
        "issue_date": TODAY,
        "customer_id": 5,
    }
    return Quote(**{**values, **overrides})


def line(**overrides: Any) -> QuoteItem:
    values: dict[str, Any] = {
        "id": 1,
        "quote_id": 1,
        "product_id": CEMENT.id,
        "quantity": Decimal(2),
        "unit_price": Decimal("9.50"),
        "presentation_id": CEMENT_BASE.id,
    }
    item = QuoteItem(**{**values, **overrides})
    item.recalculate_tax()
    return item


def catalog() -> tuple[Mock, Mock]:
    products = Mock()
    products.get_by_id.side_effect = PRODUCTS.get
    products.get_by_ids.side_effect = lambda ids: [
        PRODUCTS[i] for i in set(ids) if i in PRODUCTS
    ]
    presentation_repo = Mock()
    presentation_repo.get_by_id.side_effect = PRESENTATIONS.get
    presentation_repo.get_by_ids.side_effect = lambda ids: [
        PRESENTATIONS[i] for i in set(ids) if i in PRESENTATIONS
    ]
    return products, presentation_repo


def pricing(resolver=None, presentations=None) -> QuotePricing:
    products, presentation_repo = catalog()
    return QuotePricing(
        products,
        presentation_repo,
        presentations or QuotePresentations(),
        resolver or price_resolver(),
    )


def views(sale=None, customers=None, items=None) -> QuoteViews:
    products, _ = catalog()
    customer_repo = Mock()
    customer_repo.get_by_ids.side_effect = lambda ids: [
        c for c in (customers or []) if c.id in set(ids)
    ]
    branches = Mock()
    branches.get_by_ids.side_effect = lambda ids: [
        SimpleNamespace(
            id=i, name="Matriz", establishment_code="001", require_id=lambda i=i: i
        )
        for i in set(ids)
    ]
    sales = Mock()
    sales.first.return_value = sale
    return QuoteViews(
        items or InMemoryQuoteItems(),
        customer_repo,
        branches,
        products,
        QuotePresentations(),
        sales,
    )
