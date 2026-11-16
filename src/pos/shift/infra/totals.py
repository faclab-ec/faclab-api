from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.pos.cash.infra.models import CashMovementModel
from src.pos.refund.infra.models import RefundModel, RefundPaymentModel
from src.pos.shift.app.totals import ShiftTotalsReader
from src.pos.shift.domain.closing import ItemSold, MethodTotal, ShiftTotals
from src.receivables.infra.models import CustomerPaymentModel
from src.sales.domain.entities import COMPLETED_SALE_STATUSES
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.infra.tenant import tenant_criteria

ZERO = Decimal("0")


@injectable(lifetime="scoped", as_type=ShiftTotalsReader)
class SqlAlchemyShiftTotalsReader(ShiftTotalsReader):
    """The queries of what a shift moved (S5.9), each limited to the context
    tenant: completed sales (CONFIRMED or INVOICED) and their applied payments,
    payments on account, completed refunds and what they gave back, cash
    movements and the products sold"""

    def __init__(self, session: Session):
        self.session = session

    def of_shift(self, shift_id: int) -> ShiftTotals:
        sales = (
            self.session.query(
                func.count(SaleModel.id).label("count"),
                func.coalesce(func.sum(SaleModel.subtotal), ZERO).label("subtotal"),
                func.coalesce(func.sum(SaleModel.tax), ZERO).label("tax"),
                func.coalesce(func.sum(SaleModel.discount), ZERO).label("discount"),
                func.coalesce(func.sum(SaleModel.total), ZERO).label("total"),
            )
            .filter(SaleModel.shift_id == shift_id, *tenant_criteria(SaleModel))
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .one()
        )
        refunds = (
            self.session.query(
                func.count(RefundModel.id).label("count"),
                func.coalesce(func.sum(RefundModel.total), ZERO).label("total"),
            )
            .filter(RefundModel.shift_id == shift_id, *tenant_criteria(RefundModel))
            .filter(RefundModel.status == "COMPLETED")
            .one()
        )
        return ShiftTotals(
            sales_count=sales.count,
            sales_subtotal=sales.subtotal,
            sales_tax=sales.tax,
            sales_discount=sales.discount,
            sales_total=sales.total,
            payments=self._payments(shift_id),
            customer_payments=self._customer_payments(shift_id),
            refunds_count=refunds.count,
            refunds_total=refunds.total,
            refund_payments=self._refund_payments(shift_id),
            cash_in=self._cash_movements(shift_id, "IN"),
            cash_out=self._cash_movements(shift_id, "OUT"),
            items_sold=self._items_sold(shift_id),
        )

    def _payments(self, shift_id: int) -> list[MethodTotal]:
        """The applied payments of the shift's completed sales, by method"""
        rows = (
            self.session.query(
                PaymentModel.payment_method,
                func.count(PaymentModel.id).label("count"),
                func.sum(PaymentModel.amount).label("total"),
            )
            .join(SaleModel, SaleModel.id == PaymentModel.sale_id)
            .filter(
                SaleModel.shift_id == shift_id,
                *tenant_criteria(PaymentModel, SaleModel),
            )
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .group_by(PaymentModel.payment_method)
            .order_by(PaymentModel.payment_method)
            .all()
        )
        return [MethodTotal(row.payment_method, row.count, row.total) for row in rows]

    def _customer_payments(self, shift_id: int) -> list[MethodTotal]:
        """Payments on account taken in the shift (S5.5), by method"""
        rows = (
            self.session.query(
                CustomerPaymentModel.payment_method,
                func.count(CustomerPaymentModel.id).label("count"),
                func.sum(CustomerPaymentModel.amount).label("total"),
            )
            .filter(
                CustomerPaymentModel.shift_id == shift_id,
                *tenant_criteria(CustomerPaymentModel),
            )
            .group_by(CustomerPaymentModel.payment_method)
            .order_by(CustomerPaymentModel.payment_method)
            .all()
        )
        return [MethodTotal(row.payment_method, row.count, row.total) for row in rows]

    def _refund_payments(self, shift_id: int) -> list[MethodTotal]:
        """What the shift's completed refunds gave back, by method"""
        rows = (
            self.session.query(
                RefundPaymentModel.payment_method,
                func.count(RefundPaymentModel.id).label("count"),
                func.sum(RefundPaymentModel.amount).label("total"),
            )
            .join(RefundModel, RefundModel.id == RefundPaymentModel.refund_id)
            .filter(
                RefundModel.shift_id == shift_id,
                *tenant_criteria(RefundPaymentModel, RefundModel),
            )
            .filter(RefundModel.status == "COMPLETED")
            .group_by(RefundPaymentModel.payment_method)
            .order_by(RefundPaymentModel.payment_method)
            .all()
        )
        return [MethodTotal(row.payment_method, row.count, row.total) for row in rows]

    def _cash_movements(self, shift_id: int, type_: str) -> Decimal:
        return (
            self.session.query(func.coalesce(func.sum(CashMovementModel.amount), ZERO))
            .filter(
                CashMovementModel.shift_id == shift_id,
                *tenant_criteria(CashMovementModel),
            )
            .filter(CashMovementModel.type == type_)
            .scalar()
        )

    def _items_sold(self, shift_id: int) -> list[ItemSold]:
        rows = (
            self.session.query(
                ProductModel.name.label("product_name"),
                ProductModel.sku,
                # In base units: boxes and units of a product add up (S5.2)
                func.sum(SaleItemModel.base_quantity).label("quantity"),
                func.sum(SaleItemModel.quantity * SaleItemModel.unit_price).label(
                    "total"
                ),
            )
            .join(SaleModel, SaleModel.id == SaleItemModel.sale_id)
            .join(ProductModel, ProductModel.id == SaleItemModel.product_id)
            .filter(
                SaleModel.shift_id == shift_id,
                *tenant_criteria(SaleItemModel, SaleModel, ProductModel),
            )
            .filter(SaleModel.status.in_(COMPLETED_SALE_STATUSES))
            .group_by(ProductModel.name, ProductModel.sku)
            .order_by(ProductModel.name, ProductModel.sku)
            .all()
        )
        return [
            ItemSold(
                product_name=row.product_name,
                sku=row.sku,
                quantity=Decimal(str(row.quantity)),
                total=Decimal(str(row.total)),
            )
            for row in rows
        ]
