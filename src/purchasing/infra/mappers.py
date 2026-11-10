from typing import Any

from wireup import injectable

from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.purchasing.infra.models import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
)
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class PurchaseOrderMapper(Mapper[PurchaseOrder, PurchaseOrderModel]):
    __entity__ = PurchaseOrder
    __exclude_fields__ = frozenset({"created_at", "updated_at"})


@injectable(lifetime="singleton")
class PurchaseOrderItemMapper(Mapper[PurchaseOrderItem, PurchaseOrderItemModel]):
    __entity__ = PurchaseOrderItem


@injectable(lifetime="singleton")
class PurchaseReceiptMapper(Mapper[PurchaseReceipt, PurchaseReceiptModel]):
    __entity__ = PurchaseReceipt
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class PurchaseReceiptItemMapper(Mapper[PurchaseReceiptItem, PurchaseReceiptItemModel]):
    __entity__ = PurchaseReceiptItem

    def to_dict(self, entity: PurchaseReceiptItem) -> dict[str, Any]:
        # What went into stock, in base units (S5.2)
        return {**super().to_dict(entity), "base_quantity": entity.base_quantity}
