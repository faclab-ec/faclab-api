from abc import abstractmethod
from collections.abc import Iterable

from src.pricing.domain.entities import PriceList, PriceListItem
from src.shared.app.repositories import Repository


class PriceListRepository(Repository[PriceList]):
    @abstractmethod
    def default(self) -> PriceList | None:
        """La lista general de la empresa"""

    @abstractmethod
    def page(
        self, is_active: bool | None, limit: int | None, offset: int | None
    ) -> dict:
        """Las listas, la general primero y luego por nombre"""


class PriceListItemRepository(Repository[PriceListItem]):
    @abstractmethod
    def for_products(
        self, price_list_ids: Iterable[int], product_ids: Iterable[int]
    ) -> list[PriceListItem]:
        """Los ítems de esos productos en esas listas, con una consulta"""

    @abstractmethod
    def page(
        self,
        price_list_id: int,
        product_id: int | None,
        limit: int | None,
        offset: int | None,
    ) -> dict:
        """Los ítems de una lista por producto, presentación y cantidad mínima"""
