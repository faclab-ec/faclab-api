from abc import abstractmethod
from collections.abc import Iterable

from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierReturn,
    SupplierReturnItem,
)
from src.shared.app.repositories import Repository


class PurchaseOrderRepository(Repository[PurchaseOrder]):
    pass


class PurchaseOrderItemRepository(Repository[PurchaseOrderItem]):
    @abstractmethod
    def lock(self, ids: Iterable[int]) -> list[PurchaseOrderItem]:
        """The order lines, locked in id order until the transaction ends: a
        supplier return holds them while it counts what it gives back"""


class PurchaseReceiptRepository(Repository[PurchaseReceipt]):
    pass


class PurchaseReceiptItemRepository(Repository[PurchaseReceiptItem]):
    pass


class SupplierReturnRepository(Repository[SupplierReturn]):
    @abstractmethod
    def first_for_update(self, **kwargs) -> SupplierReturn | None:
        """Like first(), locking the row until the transaction ends"""


class SupplierReturnItemRepository(Repository[SupplierReturnItem]):
    pass
