from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.pos.shift.infra.models import ShiftModel
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetXReportQuery(Query):
    shift_id: int


@injectable(lifetime="scoped")
class GetXReportQueryHandler(QueryHandler[GetXReportQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetXReportQuery) -> dict:
        shift = self.session.get(ShiftModel, query.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {query.shift_id} not found")

        # Sales summary
        sales_agg = (
            self.session.query(
                func.count(SaleModel.id).label("count"),
                func.coalesce(func.sum(SaleModel.subtotal), Decimal("0")).label(
                    "subtotal"
                ),
                func.coalesce(func.sum(SaleModel.tax), Decimal("0")).label("tax"),
                func.coalesce(func.sum(SaleModel.discount), Decimal("0")).label(
                    "discount"
                ),
                func.coalesce(func.sum(SaleModel.total), Decimal("0")).label("total"),
            )
            .filter(SaleModel.shift_id == query.shift_id)
            .filter(SaleModel.status == "CONFIRMED")
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
            .filter(SaleModel.shift_id == query.shift_id)
            .filter(SaleModel.status == "CONFIRMED")
            .group_by(PaymentModel.payment_method)
            .all()
        )

        # Items sold
        items_rows = (
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
            .filter(SaleModel.shift_id == query.shift_id)
            .filter(SaleModel.status == "CONFIRMED")
            .group_by(ProductModel.name, ProductModel.sku)
            .all()
        )

        return {
            "shift": {
                "id": shift.id,
                "cashier_name": shift.cashier_name,
                "opened_at": shift.opened_at.isoformat() if shift.opened_at else None,
                "status": shift.status,
            },
            "sales_summary": {
                "count": sales_agg.count,
                "subtotal": sales_agg.subtotal,
                "tax": sales_agg.tax,
                "discount": sales_agg.discount,
                "total": sales_agg.total,
            },
            "payments_by_method": [
                {
                    "payment_method": row.payment_method,
                    "count": row.count,
                    "total": row.total,
                }
                for row in payments_rows
            ],
            "items_sold": [
                {
                    "product_name": row.product_name,
                    "sku": row.sku,
                    "quantity": row.quantity,
                    "total": row.total,
                }
                for row in items_rows
            ],
        }
