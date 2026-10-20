from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.numbering import DocumentType
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.pos.terminal.app.resolver import TerminalRequest, TerminalResolver
from src.pos.terminal.app.stock import TerminalStock
from src.sales.app.repositories import (
    PaymentRepository,
    SaleItemRepository,
    SaleRepository,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem
from src.sales.domain.events import SaleConfirmed, sale_items_data, sale_payments_data
from src.sales.domain.exceptions import OverrideReasonRequiredError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class QuickSaleCommand(Command):
    """Comando para venta rapida (checkout completo en un request)"""

    terminal: TerminalRequest
    items: list[dict]
    payments: list[dict]
    customer_id: int | None = None
    discount_type: str | None = None
    discount_value: Decimal = Decimal("0")
    notes: str | None = None
    created_by: str | None = None


@injectable(lifetime="scoped")
class QuickSaleCommandHandler(CommandHandler[QuickSaleCommand, dict]):
    """Handler para venta rapida: crea venta, items, confirma, paga en una transaccion"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        product_repo: ProductRepository,
        stock: TerminalStock,
        payment_repo: PaymentRepository,
        shift_repo: ShiftRepository,
        terminals: TerminalResolver,
        numbering: DocumentNumbering,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.product_repo = product_repo
        self.stock = stock
        self.payment_repo = payment_repo
        self.shift_repo = shift_repo
        self.terminals = terminals
        self.numbering = numbering
        self.event_publisher = event_publisher

    def _handle(self, command: QuickSaleCommand) -> dict:
        # 1. Obtener el turno abierto de la terminal
        terminal = self.terminals.terminal(command.terminal)
        shift = self.shift_repo.first(terminal_id=terminal.id, status="OPEN")
        if shift is None:
            raise NoOpenShiftError()

        # 2. Determinar cliente
        is_final_consumer = command.customer_id is None
        customer_id = None if is_final_consumer else command.customer_id

        # 3. Crear venta en DRAFT
        sale = Sale(
            customer_id=customer_id,
            is_final_consumer=is_final_consumer,
            shift_id=shift.id,
            branch_id=terminal.branch_id,
            emission_point_id=terminal.emission_point_id,
            terminal_id=terminal.id,
            notes=command.notes,
            created_by=command.created_by,
        )
        if command.discount_type is not None:
            sale.apply_discount(command.discount_type, command.discount_value)
        sale = self.sale_repo.create(sale)

        # 4. Crear items
        created_items = []
        for item_data in command.items:
            product = self.product_repo.get_by_id(item_data["product_id"])
            if not product:
                raise NotFoundError(
                    f"Product with id {item_data['product_id']} not found"
                )

            unit_price = Decimal(str(item_data.get("unit_price") or product.sale_price))
            # Selling at another price is recorded like POST .../price: with
            # the new price and why
            overridden = (
                product.sale_price is not None and unit_price != product.sale_price
            )
            reason = item_data.get("override_reason")
            if overridden and not reason:
                raise OverrideReasonRequiredError(product.require_id())

            sale_item = SaleItem(
                sale_id=sale.require_id(),
                product_id=product.require_id(),
                quantity=item_data["quantity"],
                unit_price=unit_price,
                discount=Decimal(str(item_data.get("discount", 0))),
                tax_code=product.tax_code,
                price_override=unit_price if overridden else None,
                override_reason=reason if overridden else None,
            )
            sale_item.recalculate_tax()
            sale_item = self.sale_item_repo.create(sale_item)
            created_items.append(sale_item)

        # 5. Recalcular totales
        sale.recalculate_totals(created_items)
        self.sale_repo.update(sale)

        # 6. Descontar el stock de la ubicación de la terminal (bloquea las filas
        #    por product_id, en orden, para que dos ventas concurrentes no se
        #    pisen ni se bloqueen mutuamente)
        self.stock.take(
            created_items,
            location_id=terminal.default_location_id,
            reason=f"Sale #{sale.id} confirmed",
            reference_type="sale",
            reference_id=sale.require_id(),
        )

        # 7. Validar pagos cubren el total
        total_payment = sum(
            (Decimal(str(p["amount"])) for p in command.payments), Decimal("0")
        )
        if not sale.is_covered_by(total_payment):
            raise ValidationError(
                message="Payment amount is insufficient",
                detail=f"Total: {sale.total}, paid: {total_payment}",
            )

        # 8. Confirmar la venta con su número de la sucursal (después del stock,
        #    como en todo documento del POS)
        sale.confirm(self.numbering.next(terminal.branch_id, DocumentType.SALE))
        self.sale_repo.update(sale)

        # 9. Registrar pagos
        created_payments = []
        for payment_data in command.payments:
            try:
                payment_method = PaymentMethod(payment_data["payment_method"])
            except ValueError:
                raise ValidationError(
                    message=f"Invalid payment method: {payment_data['payment_method']}",
                    detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
                ) from None

            payment = Payment(
                sale_id=sale.require_id(),
                amount=Decimal(str(payment_data["amount"])),
                payment_method=payment_method,
                reference=payment_data.get("reference"),
            )
            payment = self.payment_repo.create(payment)
            created_payments.append(payment)

        # 10. Actualizar estado de pago
        sale.update_payment_status(total_payment)
        self.sale_repo.update(sale)

        # 11. Publicar evento
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
                source="pos",
            )
        )

        # 12. Retornar venta completa
        result = sale.dict()
        result["items"] = [
            {**item.dict(), "subtotal": item.subtotal} for item in created_items
        ]
        result["payments"] = [p.dict() for p in created_payments]
        return result
