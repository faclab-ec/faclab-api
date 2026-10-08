from abc import abstractmethod

from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.shared.app.repositories import Repository


class PurchaseOrderRepository(Repository[PurchaseOrder]):
    @abstractmethod
    def last_sequence_for_prefix(self, prefix: str) -> int:
        """Highest numeric suffix among order numbers starting with `prefix`
        (0 if there are none)."""
        raise NotImplementedError


class PurchaseOrderItemRepository(Repository[PurchaseOrderItem]):
    pass


class PurchaseReceiptRepository(Repository[PurchaseReceipt]):
    pass


class PurchaseReceiptItemRepository(Repository[PurchaseReceiptItem]):
    pass
