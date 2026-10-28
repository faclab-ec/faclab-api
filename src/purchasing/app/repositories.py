from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.shared.app.repositories import Repository


class PurchaseOrderRepository(Repository[PurchaseOrder]):
    pass


class PurchaseOrderItemRepository(Repository[PurchaseOrderItem]):
    pass


class PurchaseReceiptRepository(Repository[PurchaseReceipt]):
    pass


class PurchaseReceiptItemRepository(Repository[PurchaseReceiptItem]):
    pass
