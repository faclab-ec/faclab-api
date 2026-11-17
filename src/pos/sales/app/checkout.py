"""The checkout of a sale in one transaction: the POS's quick sale at a terminal
and the sales of the public API (S6.3) are made the same way.

A sale is created, its lines priced by its lists (S5.3) in their presentation
(S5.2), its payments applied, its stock taken from one location, what is left
on credit opened on the customer's account (S5.5), and it is confirmed with
the number of its branch. The locks follow the order of every POS document:
the stock rows (by product), the customer, the counter last.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.pos.sales.app.commands.apply_discount import audit_discount
from src.pos.terminal.app.stock import TerminalStock
from src.pricing.app.resolver import PriceResolver
from src.quotes.app.conversion import QuoteConversion
from src.quotes.domain.entities import Quote
from src.receivables.app.credit import CustomerCredit
from src.sales.app.price_override import audit_price_override
from src.sales.app.repositories import (
    PaymentRepository,
    SaleItemRepository,
    SaleRepository,
)
from src.sales.domain.entities import (
    Payment,
    PaymentMethod,
    Sale,
    SaleChannel,
    SaleItem,
)
from src.sales.domain.events import SaleConfirmed, sale_items_data, sale_payments_data
from src.sales.domain.pricing import line_price
from src.shared.app.audit import AuditTrail
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass(frozen=True)
class SalePlacement:
    """Where a sale is made: its branch and emission point, the location its
    stock leaves from and, at the POS, its terminal and shift. A sale of the
    public API names the integration client and the order of its system."""

    branch_id: int
    emission_point_id: int
    location_id: int | None
    terminal_id: int | None = None
    shift_id: int | None = None
    channel: SaleChannel = SaleChannel.POS
    integration_client_id: int | None = None
    external_reference: str | None = None

    @property
    def source(self) -> str:
        """`SaleConfirmed.source`"""
        return self.channel.value


@dataclass
class SaleOrder:
    """What is sold: the lines (`product_id`, `quantity`, optional
    `presentation_id`, `unit_price`, `override_reason`, `discount`) and the
    payments (`amount`, `payment_method`, optional `reference`)"""

    items: list[dict]
    payments: list[dict]
    customer_id: int | None = None
    discount_type: str | None = None
    discount_value: Decimal = Decimal("0")
    notes: str | None = None
    created_by: str | None = None


@injectable(lifetime="scoped")
class SaleCheckout:
    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        product_repo: ProductRepository,
        stock: TerminalStock,
        payment_repo: PaymentRepository,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
        session: Session,
        audit: AuditTrail,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
        prices: PriceResolver,
        quotes: QuoteConversion,
        credit: CustomerCredit,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.product_repo = product_repo
        self.stock = stock
        self.payment_repo = payment_repo
        self.numbering = numbering
        self.event_publisher = event_publisher
        self.session = session
        self.audit = audit
        self.quantities = quantities
        self.presentations = presentations
        self.prices = prices
        self.quotes = quotes
        self.credit = credit

    def complete(
        self, placement: SalePlacement, order: SaleOrder, quote: Quote | None = None
    ) -> dict:
        """Creates, pays and confirms the sale; returns it with its items and
        payments. `quote`, already locked, is the one it converts (S5.4)."""
        # 1. The sale in DRAFT; without a customer, to the final consumer
        is_final_consumer = order.customer_id is None
        customer_id = None if is_final_consumer else order.customer_id
        sale = Sale(
            customer_id=customer_id,
            is_final_consumer=is_final_consumer,
            shift_id=placement.shift_id,
            branch_id=placement.branch_id,
            emission_point_id=placement.emission_point_id,
            terminal_id=placement.terminal_id,
            quote_id=quote.id if quote else None,
            channel=placement.channel,
            external_reference=placement.external_reference,
            integration_client_id=placement.integration_client_id,
            notes=order.notes,
            created_by=order.created_by,
        )
        if order.discount_type is not None:
            sale.apply_discount(order.discount_type, order.discount_value)
        sale = self.sale_repo.create(sale)

        # 2. Its lines, each at the price of its list: the customer's, the
        #    branch's or the general one (S5.3)
        chain = self.prices.chain(customer_id, placement.branch_id)
        created_items = []
        for item_data in order.items:
            product = self.product_repo.get_by_id(item_data["product_id"])
            if not product:
                raise NotFoundError(
                    f"Product with id {item_data['product_id']} not found"
                )
            # The presentation it is sold in, the base unit by default (S5.2)
            presentation = self.presentations.resolve(
                product, item_data.get("presentation_id")
            )
            quantity = Decimal(str(item_data["quantity"]))
            self.quantities.ensure_for_presentation(
                product, presentation.factor, quantity
            )

            list_price = self.prices.price(
                chain, product, presentation, quantity
            ).unit_price
            # Selling at another price is recorded like PUT .../price: with
            # the new price and why
            reason = item_data.get("override_reason")
            unit_price, overridden = line_price(
                product.require_id(), list_price, item_data.get("unit_price"), reason
            )

            sale_item = SaleItem(
                sale_id=sale.require_id(),
                product_id=product.require_id(),
                quantity=quantity,
                unit_price=unit_price,
                discount=Decimal(str(item_data.get("discount", 0))),
                tax_code=product.tax_code,
                price_override=unit_price if overridden else None,
                override_reason=reason if overridden else None,
                presentation_id=presentation.id,
                unit_factor=presentation.factor,
            )
            sale_item.recalculate_tax()
            sale_item = self.sale_item_repo.create(sale_item)
            created_items.append(sale_item)
            if overridden:
                audit_price_override(self.audit, sale, sale_item, list_price)

        # Its same items: product, presentation, quantity and discount
        if quote is not None:
            self.quotes.ensure_items(quote, created_items)

        # 3. The totals
        sale.recalculate_totals(created_items)
        if sale.discount_value > 0:
            audit_discount(self.audit, sale)

        # 4. The payments applied to the total: each amount is what the
        #    customer hands over, what is still owed is applied and the rest in
        #    cash is the change; a CREDIT payment leaves its amount on credit
        #    (S5.5). Before locking the stock
        payments = [
            Payment(
                sale_id=sale.require_id(),
                amount=Decimal(str(payment_data["amount"])),
                payment_method=payment_method(payment_data["payment_method"]),
                reference=payment_data.get("reference"),
            )
            for payment_data in order.payments
        ]
        on_credit = sale.settle(payments) > 0
        self.sale_repo.update(sale)

        # 5. The stock leaves its location (locks the rows by product_id, in
        #    order, so two concurrent sales neither overwrite nor deadlock)
        self.stock.take(
            created_items,
            location_id=placement.location_id,
            reason=f"Sale #{sale.id} confirmed",
            reference_type="sale",
            reference_id=sale.require_id(),
        )

        # 6. What is left on credit goes to the customer's account, within its
        #    limit: locks its row after the stock and before the counter
        self.credit.open(sale, payments)

        # 7. Confirmed with the number of its branch (after the stock, like
        #    every POS document)
        sale.confirm(
            self.numbering.next(placement.branch_id, DocumentType.SALE),
            on_credit=on_credit,
        )
        self.sale_repo.update(sale)
        if quote is not None:
            self.quotes.convert(quote)

        # 8. The payments
        created_payments = [self.payment_repo.create(p) for p in payments]

        # 9. Its sales.confirmed message goes to the outbox in this transaction
        self.event_publisher.publish(
            SaleConfirmed(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                items=sale_items_data(created_items),
                subtotal=sale.subtotal,
                total_discount=sale.discount,
                total=sale.total,
                payments=sale_payments_data(created_payments),
                source=placement.source,
                branch_id=sale.branch_id,
                emission_point_id=sale.emission_point_id,
                number=sale.number,
            ),
            session=self.session,
        )

        # 10. The whole sale, with the invoice the invoicing handler left
        #     pending
        result = (self.sale_repo.get_by_id(sale.require_id()) or sale).dict()
        names = self.presentations.names(i.presentation_id for i in created_items)
        result["items"] = [
            {
                **item.dict(),
                "subtotal": item.subtotal,
                "presentation_name": names.get(item.presentation_id or 0),
            }
            for item in created_items
        ]
        result["payments"] = [p.dict() for p in created_payments]
        return result


def payment_method(value: str) -> PaymentMethod:
    try:
        return PaymentMethod(value)
    except ValueError:
        raise ValidationError(
            message=f"Invalid payment method: {value}",
            detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
        ) from None
