from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.payables.app.repositories import (
    PayableApplicationRepository,
    PayableRepository,
    SupplierPaymentRepository,
)
from src.payables.domain.entities import (
    Payable,
    PayableApplication,
    PayableStatus,
    SupplierPayment,
)
from src.payables.infra.mappers import (
    PayableApplicationMapper,
    PayableMapper,
    SupplierPaymentMapper,
)
from src.payables.infra.models import (
    PayableApplicationModel,
    PayableModel,
    SupplierPaymentModel,
)
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=PayableRepository)
class SqlAlchemyPayableRepository(SqlAlchemyRepository[Payable], PayableRepository):
    __model__ = PayableModel

    def __init__(self, session: Session, mapper: PayableMapper):
        super().__init__(session, mapper)

    # FOR NO KEY UPDATE: an application being inserted holds FOR KEY SHARE on
    # its payable (its foreign key), which FOR UPDATE would wait for. The key
    # never changes, and two writers of a payable still take turns
    def open_for_update(self, supplier_id: int) -> list[Payable]:
        models = (
            self._query()
            .filter(
                PayableModel.supplier_id == supplier_id,
                PayableModel.status == PayableStatus.OPEN.value,
            )
            .order_by(PayableModel.id)
            .with_for_update(key_share=True)
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]

    def outstanding(self, supplier_id: int) -> Decimal:
        total = (
            self._query(func.coalesce(func.sum(PayableModel.balance), 0))
            .filter(
                PayableModel.supplier_id == supplier_id,
                PayableModel.status == PayableStatus.OPEN.value,
            )
            .scalar()
        )
        return Decimal(total or 0)


@injectable(lifetime="scoped", as_type=PayableApplicationRepository)
class SqlAlchemyPayableApplicationRepository(
    SqlAlchemyRepository[PayableApplication], PayableApplicationRepository
):
    __model__ = PayableApplicationModel

    def __init__(self, session: Session, mapper: PayableApplicationMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=SupplierPaymentRepository)
class SqlAlchemySupplierPaymentRepository(
    SqlAlchemyRepository[SupplierPayment], SupplierPaymentRepository
):
    __model__ = SupplierPaymentModel

    def __init__(self, session: Session, mapper: SupplierPaymentMapper):
        super().__init__(session, mapper)
