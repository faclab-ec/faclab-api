from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.receivables.app.repositories import (
    CustomerPaymentRepository,
    ReceivableApplicationRepository,
    ReceivableRepository,
)
from src.receivables.domain.entities import (
    CustomerPayment,
    Receivable,
    ReceivableApplication,
    ReceivableStatus,
)
from src.receivables.infra.mappers import (
    CustomerPaymentMapper,
    ReceivableApplicationMapper,
    ReceivableMapper,
)
from src.receivables.infra.models import (
    CustomerPaymentModel,
    ReceivableApplicationModel,
    ReceivableModel,
)
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=ReceivableRepository)
class SqlAlchemyReceivableRepository(
    SqlAlchemyRepository[Receivable], ReceivableRepository
):
    __model__ = ReceivableModel

    def __init__(self, session: Session, mapper: ReceivableMapper):
        super().__init__(session, mapper)

    # FOR NO KEY UPDATE: an application being inserted holds FOR KEY SHARE on
    # its receivable (its foreign key), which FOR UPDATE would wait for. The key
    # never changes, and two writers of a receivable still take turns

    def first_for_update(self, **kwargs) -> Receivable | None:
        criteria = [
            getattr(ReceivableModel, key) == value for key, value in kwargs.items()
        ]
        model = self._query().filter(*criteria).with_for_update(key_share=True).first()
        return self.mapper.to_entity(model)

    def open_for_update(self, customer_id: int) -> list[Receivable]:
        models = (
            self._query()
            .filter(
                ReceivableModel.customer_id == customer_id,
                ReceivableModel.status == ReceivableStatus.OPEN.value,
            )
            .order_by(ReceivableModel.id)
            .with_for_update(key_share=True)
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]

    def outstanding(self, customer_id: int) -> Decimal:
        total = (
            self._query(func.coalesce(func.sum(ReceivableModel.balance), 0))
            .filter(
                ReceivableModel.customer_id == customer_id,
                ReceivableModel.status == ReceivableStatus.OPEN.value,
            )
            .scalar()
        )
        return Decimal(total or 0)


@injectable(lifetime="scoped", as_type=ReceivableApplicationRepository)
class SqlAlchemyReceivableApplicationRepository(
    SqlAlchemyRepository[ReceivableApplication], ReceivableApplicationRepository
):
    __model__ = ReceivableApplicationModel

    def __init__(self, session: Session, mapper: ReceivableApplicationMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=CustomerPaymentRepository)
class SqlAlchemyCustomerPaymentRepository(
    SqlAlchemyRepository[CustomerPayment], CustomerPaymentRepository
):
    __model__ = CustomerPaymentModel

    def __init__(self, session: Session, mapper: CustomerPaymentMapper):
        super().__init__(session, mapper)
