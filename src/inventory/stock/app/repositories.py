from abc import abstractmethod

from src.inventory.stock.domain.entities import Stock
from src.shared.app.repositories import Repository


class StockRepository(Repository[Stock]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> Stock | None:
        """Like first(), but locks the row until the transaction ends. Use it
        before changing a quantity so concurrent sales can't both read the same
        stock and overwrite each other."""
        raise NotImplementedError
