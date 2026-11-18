from dataclasses import dataclass

from src.shared.domain.events import DomainEvent


@dataclass
class ProductCreated(DomainEvent):
    product_id: int = 0
    sku: str = ""
    name: str = ""
    category_id: int | None = None

    def _payload(self) -> dict:
        return {
            "product_id": self.product_id,
            "sku": self.sku,
            "name": self.name,
            "category_id": self.category_id,
        }


@dataclass
class ProductUpdated(DomainEvent):
    product_id: int = 0
    changes: dict | None = None

    def _payload(self) -> dict:
        return {
            "product_id": self.product_id,
            "changes": self.changes or {},
        }


@dataclass
class ProductPresentationChanged(DomainEvent):
    """A presentation of the product was created, changed or deleted: its
    product changed for whoever reads it (S6.4, `product.updated`)"""

    product_id: int = 0
    presentation_id: int = 0

    def _payload(self) -> dict:
        return {"product_id": self.product_id, "presentation_id": self.presentation_id}


@dataclass
class ProductDeleted(DomainEvent):
    product_id: int = 0

    def _payload(self) -> dict:
        return {"product_id": self.product_id}


@dataclass
class CategoryCreated(DomainEvent):
    category_id: int = 0
    name: str = ""

    def _payload(self) -> dict:
        return {
            "category_id": self.category_id,
            "name": self.name,
        }


@dataclass
class CategoryUpdated(DomainEvent):
    category_id: int = 0
    changes: dict | None = None

    def _payload(self) -> dict:
        return {
            "category_id": self.category_id,
            "changes": self.changes or {},
        }


@dataclass
class CategoryDeleted(DomainEvent):
    category_id: int = 0

    def _payload(self) -> dict:
        return {"category_id": self.category_id}
