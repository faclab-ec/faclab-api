from sqlalchemy.orm import Session
from wireup import injectable

from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    PurchaseReceiptItemRepository,
    PurchaseReceiptRepository,
)
from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from src.purchasing.domain.exceptions import PurchaseOrderNumberAlreadyExistsError
from src.purchasing.infra.mappers import (
    PurchaseOrderItemMapper,
    PurchaseOrderMapper,
    PurchaseReceiptItemMapper,
    PurchaseReceiptMapper,
)
from src.purchasing.infra.models import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
)
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=PurchaseOrderRepository)
class SqlAlchemyPurchaseOrderRepository(
    SqlAlchemyRepository[PurchaseOrder], PurchaseOrderRepository
):
    __model__ = PurchaseOrderModel
    __unique_errors__ = {
        "uq_purchase_orders_tenant_order_number": PurchaseOrderNumberAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: PurchaseOrderMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=PurchaseOrderItemRepository)
class SqlAlchemyPurchaseOrderItemRepository(
    SqlAlchemyRepository[PurchaseOrderItem], PurchaseOrderItemRepository
):
    __model__ = PurchaseOrderItemModel

    def __init__(self, session: Session, mapper: PurchaseOrderItemMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=PurchaseReceiptRepository)
class SqlAlchemyPurchaseReceiptRepository(
    SqlAlchemyRepository[PurchaseReceipt], PurchaseReceiptRepository
):
    __model__ = PurchaseReceiptModel

    def __init__(self, session: Session, mapper: PurchaseReceiptMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=PurchaseReceiptItemRepository)
class SqlAlchemyPurchaseReceiptItemRepository(
    SqlAlchemyRepository[PurchaseReceiptItem], PurchaseReceiptItemRepository
):
    __model__ = PurchaseReceiptItemModel

    def __init__(self, session: Session, mapper: PurchaseReceiptItemMapper):
        super().__init__(session, mapper)
