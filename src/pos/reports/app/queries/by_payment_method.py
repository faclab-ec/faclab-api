from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.sales.domain.entities import COMPLETED_SALE_STATUSES
from src.sales.infra.models import PaymentModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetSalesByPaymentMethodQuery(Query):
    from_date: date | None = None
    to_date: date | None = None


@injectable(lifetime="scoped")
class GetSalesByPaymentMethodQueryHandler(
    QueryHandler[GetSalesByPaymentMethodQuery, list]
):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetSalesByPaymentMethodQuery) -> list:
        q = (
            self.session.query(
                PaymentModel.payment_method,
                func.count(func.distinct(SaleModel.id)).label("sales_count"),
                func.sum(PaymentModel.amount).label("total_amount"),
            )
            .join(SaleModel, SaleModel.id == PaymentModel.sale_id)
            .filter(*tenant_criteria(PaymentModel, SaleModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
        )

        if query.from_date is not None:
            q = q.filter(
                SaleModel.sale_date >= datetime.combine(query.from_date, time.min)
            )
        if query.to_date is not None:
            q = q.filter(
                SaleModel.sale_date <= datetime.combine(query.to_date, time.max)
            )

        rows = q.group_by(PaymentModel.payment_method).all()

        return [
            {
                "payment_method": row.payment_method,
                "sales_count": row.sales_count,
                "total_amount": row.total_amount,
            }
            for row in rows
        ]
