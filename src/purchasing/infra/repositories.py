from collections.abc import Iterable

from sqlalchemy.orm import Session
from wireup import injectable

from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
    PurchaseReceiptItemRepository,
    PurchaseReceiptRepository,
    SupplierReturnItemRepository,
    SupplierReturnRepository,
)
from src.purchasing.domain.entities import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierReturn,
    SupplierReturnItem,
)
from src.purchasing.domain.exceptions import (
    PurchaseOrderNumberAlreadyExistsError,
    SupplierReturnNumberAlreadyExistsError,
)
from src.purchasing.infra.mappers import (
    PurchaseOrderItemMapper,
    PurchaseOrderMapper,
    PurchaseReceiptItemMapper,
    PurchaseReceiptMapper,
    SupplierReturnItemMapper,
    SupplierReturnMapper,
)
from src.purchasing.infra.models import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseReceiptItemModel,
    PurchaseReceiptModel,
    SupplierReturnItemModel,
    SupplierReturnModel,
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

    def lock(self, ids: Iterable[int]) -> list[PurchaseOrderItem]:
        models = (
            self._query()
            .filter(PurchaseOrderItemModel.id.in_(sorted(set(ids))))
            .order_by(PurchaseOrderItemModel.id)
            .with_for_update()
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]


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


@injectable(lifetime="scoped", as_type=SupplierReturnRepository)
class SqlAlchemySupplierReturnRepository(
    SqlAlchemyRepository[SupplierReturn], SupplierReturnRepository
):
    __model__ = SupplierReturnModel
    __unique_errors__ = {
        "uq_supplier_returns_tenant_number": SupplierReturnNumberAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: SupplierReturnMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=SupplierReturnItemRepository)
class SqlAlchemySupplierReturnItemRepository(
    SqlAlchemyRepository[SupplierReturnItem], SupplierReturnItemRepository
):
    __model__ = SupplierReturnItemModel

    def __init__(self, session: Session, mapper: SupplierReturnItemMapper):
        super().__init__(session, mapper)
