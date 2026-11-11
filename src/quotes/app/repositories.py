from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.quotes.domain.entities import Quote, QuoteItem, QuoteStatus
from src.shared.app.repositories import Repository


@dataclass(frozen=True)
class QuoteFilter:
    """Which quotes a list shows. `branch_ids` None is every branch;
    `in_force_on` keeps the open ones still valid that day (the POS)"""

    status: QuoteStatus | None = None
    customer_id: int | None = None
    branch_ids: frozenset[int] | None = None
    number: str | None = None
    search: str | None = None
    in_force_on: date | None = None


class QuoteRepository(Repository[Quote]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> Quote | None:
        """Like first(), locking the row until the transaction ends: a
        conversion holds it so a second one waits and finds it converted"""

    @abstractmethod
    def page(self, where: QuoteFilter, limit: int | None, offset: int | None) -> dict:
        """The quotes that match, newest first"""


class QuoteItemRepository(Repository[QuoteItem]):
    @abstractmethod
    def for_quote(self, quote_id: int) -> list[QuoteItem]:
        """Its items in the order they were added"""

    @abstractmethod
    def for_quotes(self, quote_ids: Sequence[int]) -> list[QuoteItem]:
        """The items of several quotes, with one query"""
