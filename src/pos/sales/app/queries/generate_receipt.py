from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.customers.infra.models import CustomerModel
from src.pos.shift.infra.models import ShiftModel
from src.sales.domain.services import discount_factor, tax_breakdown
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GenerateReceiptQuery(Query):
    """Query para generar recibo de una venta"""

    sale_id: int


@injectable(lifetime="scoped")
class GenerateReceiptQueryHandler(QueryHandler[GenerateReceiptQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GenerateReceiptQuery) -> dict:
        sale = (
            self.session.query(SaleModel)
            .filter(SaleModel.id == query.sale_id, *tenant_criteria(SaleModel))
            .first()
        )
        if not sale:
            raise NotFoundError(f"Sale with id {query.sale_id} not found")

        # Fetch items with product names
        item_rows = (
            self.session.query(SaleItemModel, ProductModel.name)
            .join(ProductModel, ProductModel.id == SaleItemModel.product_id)
            .filter(
                SaleItemModel.sale_id == query.sale_id,
                *tenant_criteria(SaleItemModel, ProductModel),
            )
            .all()
        )

        items = []
        taxed_lines = []

        for item_model, product_name in item_rows:
            base = item_model.unit_price * item_model.quantity
            discount_amount = base * (item_model.discount / Decimal("100"))
            subtotal = base - discount_amount

            items.append(
                {
                    "product_name": product_name,
                    "quantity": item_model.quantity,
                    "unit_price": item_model.unit_price,
                    "discount": item_model.discount,
                    "discount_amount": discount_amount,
                    "tax_code": item_model.tax_code,
                    "tax_amount": item_model.tax_amount,
                    "subtotal": subtotal,
                    "price_override": item_model.price_override,
                    "override_reason": item_model.override_reason,
                }
            )

            taxed_lines.append(
                (TaxCode(item_model.tax_code), subtotal, item_model.tax_amount)
            )

        # Same per-code amounts that add up to sale.tax
        breakdown = tax_breakdown(
            taxed_lines, discount_factor(sale.subtotal, sale.discount)
        )
        tax_groups = [
            {
                "tax_code": code,
                "tax_rate": code.rate,
                "taxable_base": base,
                "tax_amount": tax,
            }
            for code, (base, tax) in sorted(
                breakdown.items(), key=lambda kv: (kv[0].rate, kv[0])
            )
        ]

        # Fetch payments
        payment_rows = (
            self.session.query(PaymentModel)
            .filter(
                PaymentModel.sale_id == query.sale_id, *tenant_criteria(PaymentModel)
            )
            .all()
        )
        payments = [
            {
                "method": p.payment_method,
                "amount": p.amount,
                "reference": p.reference,
            }
            for p in payment_rows
        ]
        total_paid = sum(p.amount for p in payment_rows)
        change = max(total_paid - sale.total, Decimal("0"))

        # Fetch customer if exists
        customer = None
        if sale.customer_id:
            cust = (
                self.session.query(CustomerModel)
                .filter(
                    CustomerModel.id == sale.customer_id,
                    *tenant_criteria(CustomerModel),
                )
                .first()
            )
            if cust:
                customer = {
                    "name": cust.name,
                    "tax_id": cust.tax_id,
                    "address": cust.address,
                }

        # Fetch cashier name from shift
        cashier = None
        if sale.shift_id:
            shift = (
                self.session.query(ShiftModel)
                .filter(ShiftModel.id == sale.shift_id, *tenant_criteria(ShiftModel))
                .first()
            )
            if shift:
                cashier = shift.cashier_name

        return {
            "sale_id": sale.id,
            "sale_date": sale.sale_date,
            "status": sale.status,
            "cashier": cashier,
            "customer": customer,
            "is_final_consumer": sale.is_final_consumer,
            "items": items,
            "tax_breakdown": tax_groups,
            "subtotal": sale.subtotal,
            "discount": sale.discount,
            "discount_type": sale.discount_type,
            "discount_value": sale.discount_value,
            "tax": sale.tax,
            "total": sale.total,
            "payments": payments,
            "total_paid": total_paid,
            "change": change,
        }
