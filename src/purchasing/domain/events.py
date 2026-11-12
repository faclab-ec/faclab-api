from dataclasses import dataclass, field
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class PurchaseOrderCreated(DomainEvent):
    purchase_order_id: int = 0
    order_number: str = ""
    supplier_id: int = 0

    def _payload(self) -> dict[str, Any]:
        return {
            "purchase_order_id": self.purchase_order_id,
            "order_number": self.order_number,
            "supplier_id": self.supplier_id,
        }


@dataclass
class PurchaseOrderSent(DomainEvent):
    purchase_order_id: int = 0
    order_number: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "purchase_order_id": self.purchase_order_id,
            "order_number": self.order_number,
        }


@dataclass
class PurchaseOrderReceived(DomainEvent):
    purchase_order_id: int = 0
    order_number: str = ""
    is_complete: bool = False
    items: list[dict[str, Any]] = field(default_factory=list)

    def _payload(self) -> dict[str, Any]:
        return {
            "purchase_order_id": self.purchase_order_id,
            "order_number": self.order_number,
            "is_complete": self.is_complete,
            "items": self.items,
        }


@dataclass
class PurchaseOrderCancelled(DomainEvent):
    purchase_order_id: int = 0
    order_number: str = ""

    def _payload(self) -> dict[str, Any]:
        return {
            "purchase_order_id": self.purchase_order_id,
            "order_number": self.order_number,
        }


@dataclass
class SupplierReturnConfirmed(DomainEvent):
    """Mercadería que vuelve al proveedor (S5.7): cada ítem sale del stock de su
    ubicación, en unidades base (`quantity`)"""

    supplier_return_id: int = 0
    number: str = ""
    purchase_order_id: int = 0
    supplier_id: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)

    def _payload(self) -> dict[str, Any]:
        return {
            "supplier_return_id": self.supplier_return_id,
            "number": self.number,
            "purchase_order_id": self.purchase_order_id,
            "supplier_id": self.supplier_id,
            "items": self.items,
        }
