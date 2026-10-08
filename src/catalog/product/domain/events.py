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
