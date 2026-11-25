from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from wireup import injectable

from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository
from src.shared.infra.tenant import tenant_criteria
from src.subscriptions.app.repositories import (
    DocumentUsageRepository,
    PlanRepository,
    SubscriptionRepository,
)
from src.subscriptions.domain.entities import DocumentUsage, Plan, Subscription
from src.subscriptions.domain.exceptions import PlanCodeAlreadyExistsError
from src.subscriptions.infra.mappers import PlanMapper, SubscriptionMapper
from src.subscriptions.infra.models import (
    DocumentUsageModel,
    PlanModel,
    SubscriptionModel,
)


@injectable(lifetime="scoped", as_type=PlanRepository)
class SqlAlchemyPlanRepository(SqlAlchemyRepository[Plan], PlanRepository):
    __model__ = PlanModel
    __unique_errors__ = {
        "plans_code_key": lambda: PlanCodeAlreadyExistsError("The plan code exists")
    }

    def __init__(self, session: Session, mapper: PlanMapper):
        super().__init__(session, mapper)

    def default(self) -> Plan | None:
        return self.first(is_default=True)


@injectable(lifetime="scoped", as_type=SubscriptionRepository)
class SqlAlchemySubscriptionRepository(
    SqlAlchemyRepository[Subscription], SubscriptionRepository
):
    __model__ = SubscriptionModel

    def __init__(self, session: Session, mapper: SubscriptionMapper):
        super().__init__(session, mapper)

    def current(self) -> Subscription | None:
        return self.first()

    def lock_current(self) -> Subscription | None:
        # FOR NO KEY UPDATE: nothing points at a subscription, but the lighter
        # lock keeps it from waiting on rows being inserted that do (S5.5)
        model = (
            self._query()
            .with_for_update(key_share=True)
            .order_by(SubscriptionModel.id)
            .first()
        )
        return self.mapper.to_entity(model)


@injectable(lifetime="scoped", as_type=DocumentUsageRepository)
class SqlAlchemyDocumentUsageRepository(DocumentUsageRepository):
    def __init__(self, session: Session):
        self.session = session

    def count(
        self, period: date, *, invoices: int = 0, credit_notes: int = 0
    ) -> DocumentUsage:
        values = {
            "tenant_id": require_tenant("counting documents").tenant_id,
            "period": period,
            "invoices": invoices,
            "credit_notes": credit_notes,
            "updated_at": datetime.now(),
        }
        bump = {
            "invoices": DocumentUsageModel.invoices + invoices,
            "credit_notes": DocumentUsageModel.credit_notes + credit_notes,
            "updated_at": datetime.now(),
        }
        insert = (
            postgresql.insert
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite.insert
        )
        statement = (
            insert(DocumentUsageModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["tenant_id", "period"], set_=bump)
            .returning(DocumentUsageModel.invoices, DocumentUsageModel.credit_notes)
        )
        row = self.session.execute(statement).one()
        return DocumentUsage(
            period=period, invoices=row.invoices, credit_notes=row.credit_notes
        )

    def months(self, periods: list[date]) -> list[DocumentUsage]:
        rows = self.session.execute(
            select(
                DocumentUsageModel.period,
                DocumentUsageModel.invoices,
                DocumentUsageModel.credit_notes,
            ).where(
                *tenant_criteria(DocumentUsageModel),
                DocumentUsageModel.period.in_(periods),
            )
        ).all()
        found = {row.period: row for row in rows}
        return [
            DocumentUsage(
                period=period,
                invoices=found[period].invoices if period in found else 0,
                credit_notes=found[period].credit_notes if period in found else 0,
            )
            for period in periods
        ]
