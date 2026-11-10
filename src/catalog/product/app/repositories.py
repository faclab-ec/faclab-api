from abc import abstractmethod
from collections.abc import Iterable

from src.catalog.product.domain.entities import Category, Product, ProductPresentation
from src.shared.app.repositories import Repository


class CategoryRepository(Repository[Category]):
    pass


class ProductRepository(Repository[Product]):
    pass


class ProductPresentationRepository(Repository[ProductPresentation]):
    @abstractmethod
    def for_products(self, product_ids: Iterable[int]) -> list[ProductPresentation]:
        """Las presentaciones de esos productos, la base primero y luego por factor"""

    @abstractmethod
    def base_of(self, product_id: int) -> ProductPresentation | None:
        """La presentación base del producto"""

    @abstractmethod
    def by_barcode(self, barcode: str) -> ProductPresentation | None:
        """La presentación con ese código de barras, activa o no"""
