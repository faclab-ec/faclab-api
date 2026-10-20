from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.pos.shift.infra.models import ShiftModel
from src.pos.terminal.app.scope import in_scope
from src.sales.domain.entities import COMPLETED_SALE_STATUSES
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria


def get_shift(
    session: Session, shift_id: int, branch_ids: frozenset[int] | None = None
) -> ShiftModel:
    """The context tenant's shift; another tenant's id, or a shift of a branch
    the user can't enter (`branch_ids`), is not found"""
    shift = (
        session.query(ShiftModel)
        .filter(ShiftModel.id == shift_id, *tenant_criteria(ShiftModel))
        .first()
    )
    if shift is None or not in_scope(shift.branch_id, branch_ids):
        raise NotFoundError(f"Shift with id {shift_id} not found")
    return shift


@dataclass
class GetXReportQuery(Query):
    shift_id: int
    # The user's branches (None: all)
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class GetXReportQueryHandler(QueryHandler[GetXReportQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetXReportQuery) -> dict:
        shift = get_shift(self.session, query.shift_id, query.branch_ids)

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
            .filter(SaleModel.shift_id == query.shift_id, *tenant_criteria(SaleModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
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
            .filter(
                SaleModel.shift_id == query.shift_id,
                *tenant_criteria(PaymentModel, SaleModel),
            )
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
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
            .filter(
                SaleModel.shift_id == query.shift_id,
                *tenant_criteria(SaleItemModel, SaleModel, ProductModel),
            )
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .group_by(ProductModel.name, ProductModel.sku)
            .all()
        )

        return {
            "shift": {
                "id": shift.id,
                "terminal_id": shift.terminal_id,
                "branch_id": shift.branch_id,
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
