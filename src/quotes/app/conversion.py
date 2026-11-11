from collections import Counter
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Protocol

from wireup import injectable

from src.quotes.app.repositories import QuoteItemRepository, QuoteRepository
from src.quotes.domain.entities import Quote
from src.quotes.domain.exceptions import (
    QuoteCustomerChangedError,
    QuoteItemsChangedError,
    QuoteOutsideBranchError,
)
from src.shared.domain.exceptions import NotFoundError


class SoldLine(Protocol):
    """A line of the sale that converts the quote"""

    @property
    def product_id(self) -> int: ...

    @property
    def presentation_id(self) -> int | None: ...

    @property
    def quantity(self) -> Decimal: ...

    @property
    def discount(self) -> Decimal: ...


def _key(line: SoldLine) -> tuple[int, int | None, Decimal, Decimal]:
    # Equal Decimals hash alike: 2 and 2.000000 are the same quantity
    return (line.product_id, line.presentation_id, line.quantity, line.discount)


@injectable(lifetime="scoped")
class QuoteConversion:
    """Una cotización cobrada en el POS (S5.4): la venta rápida que la trae
    (`quote_id`) es su conversión, en la misma transacción.

    `take` bloquea la cotización antes que el stock y el contador, así una
    segunda conversión espera y la encuentra convertida; `ensure_items` exige
    sus mismos ítems y `convert` la cierra. El precio no se compara aquí: el
    cotizado distinto del de lista va como cambio de precio con su motivo y queda
    en la auditoría (`sale.price_overridden`), como cualquier otro."""

    def __init__(self, quotes: QuoteRepository, items: QuoteItemRepository):
        self.quotes = quotes
        self.items = items

    def take(self, quote_id: int, branch_id: int, customer_id: int | None) -> Quote:
        quote = self.quotes.first_for_update(id=quote_id)
        if quote is None:
            raise NotFoundError(f"Quote with id {quote_id} not found")
        if quote.branch_id != branch_id:
            raise QuoteOutsideBranchError(quote.number)
        quote.ensure_convertible(date.today())
        if quote.customer_id != customer_id:
            raise QuoteCustomerChangedError(quote.number)
        return quote

    def ensure_items(self, quote: Quote, lines: Iterable[SoldLine]) -> None:
        expected = Counter(
            _key(item) for item in self.items.for_quote(quote.require_id())
        )
        if Counter(_key(line) for line in lines) != expected:
            raise QuoteItemsChangedError(quote.number)

    def convert(self, quote: Quote) -> None:
        quote.convert(date.today())
        self.quotes.update(quote)
