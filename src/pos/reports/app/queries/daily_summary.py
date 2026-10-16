from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.pos.refund.infra.models import RefundModel
from src.sales.domain.entities import COMPLETED_SALE_STATUSES
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetDailySummaryQuery(Query):
    date: date = field(default_factory=date.today)


@injectable(lifetime="scoped")
class GetDailySummaryQueryHandler(QueryHandler[GetDailySummaryQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetDailySummaryQuery) -> dict:
        day_start = datetime.combine(query.date, time.min)
        day_end = datetime.combine(query.date, time.max)

        # Sales summary
        sales_agg = (
            self.session.query(
                func.count(SaleModel.id).label("count"),
                func.coalesce(func.sum(SaleModel.total), Decimal("0")).label("total"),
            )
            .filter(*tenant_criteria(SaleModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .filter(SaleModel.sale_date >= day_start)
            .filter(SaleModel.sale_date <= day_end)
            .one()
        )

        # Payments by method
        payments_rows = (
            self.session.query(
                PaymentModel.payment_method,
                func.count(PaymentModel.id).label("count"),
                func.sum(PaymentModel.amount).label("total"),
            )
            .join(SaleModel, SaleModel.id == PaymentModel.sale_id)
            .filter(*tenant_criteria(PaymentModel, SaleModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .filter(SaleModel.sale_date >= day_start)
            .filter(SaleModel.sale_date <= day_end)
            .group_by(PaymentModel.payment_method)
            .all()
        )

        # Top products
        top_products = (
            self.session.query(
                ProductModel.name.label("product_name"),
                ProductModel.sku,
                func.sum(SaleItemModel.quantity).label("quantity"),
                func.sum(SaleItemModel.quantity * SaleItemModel.unit_price).label(
                    "total"
                ),
            )
            .join(SaleModel, SaleModel.id == SaleItemModel.sale_id)
            .join(ProductModel, ProductModel.id == SaleItemModel.product_id)
            .filter(*tenant_criteria(SaleItemModel, SaleModel, ProductModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .filter(SaleModel.sale_date >= day_start)
            .filter(SaleModel.sale_date <= day_end)
            .group_by(ProductModel.name, ProductModel.sku)
            .order_by(func.sum(SaleItemModel.quantity).desc())
            .limit(10)
            .all()
        )

        # Refunds
        refund_agg = (
            self.session.query(
                func.count(RefundModel.id).label("count"),
                func.coalesce(func.sum(RefundModel.total), Decimal("0")).label("total"),
            )
            .filter(*tenant_criteria(RefundModel))
            .filter(RefundModel.status == "COMPLETED")
            .filter(RefundModel.refund_date >= day_start)
            .filter(RefundModel.refund_date <= day_end)
            .one()
        )

        return {
            "date": query.date.isoformat(),
            "total_sales": sales_agg.count,
            "total_amount": sales_agg.total,
            "payments_by_method": [
                {
                    "payment_method": row.payment_method,
                    "count": row.count,
                    "total": row.total,
                }
                for row in payments_rows
            ],
            "top_products": [
                {
                    "product_name": row.product_name,
                    "sku": row.sku,
                    "quantity": row.quantity,
                    "total": row.total,
                }
                for row in top_products
            ],
            "refund_summary": {
                "count": refund_agg.count,
                "total": refund_agg.total,
            },
        }
