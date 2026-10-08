from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.app.repositories import StockRepository
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.sales.app.repositories import (
    PaymentRepository,
    SaleItemRepository,
    SaleRepository,
)
from src.sales.domain.entities import Payment, PaymentMethod, Sale, SaleItem
from src.sales.domain.events import SaleConfirmed
from src.sales.domain.exceptions import InsufficientStockError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class QuickSaleCommand(Command):
    """Comando para venta rapida (checkout completo en un request)"""

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
        movement_repo: MovementRepository,
        stock_repo: StockRepository,
        payment_repo: PaymentRepository,
        shift_repo: ShiftRepository,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.product_repo = product_repo
        self.movement_repo = movement_repo
        self.stock_repo = stock_repo
        self.payment_repo = payment_repo
        self.shift_repo = shift_repo
        self.event_publisher = event_publisher

    def _handle(self, command: QuickSaleCommand) -> dict:
        # 1. Obtener turno activo
        shift = self.shift_repo.first(status="OPEN")
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

            sale_item = SaleItem(
                sale_id=sale.require_id(),
                product_id=product.require_id(),
                quantity=item_data["quantity"],
                unit_price=Decimal(
                    str(item_data.get("unit_price") or product.sale_price)
                ),
                discount=Decimal(str(item_data.get("discount", 0))),
                tax_code=product.tax_code,
            )
            sale_item.recalculate_tax()
            sale_item = self.sale_item_repo.create(sale_item)
            created_items.append(sale_item)

        # 5. Recalcular totales
        sale.recalculate_totals(created_items)
        self.sale_repo.update(sale)

        # 6. Validar stock
        for item in created_items:
            stock = self.stock_repo.first(product_id=item.product_id)
            available = stock.quantity if stock else 0
            if available < item.quantity:
                raise InsufficientStockError(item.product_id, item.quantity, available)

        # 7. Validar pagos cubren el total
        total_payment = sum(
            (Decimal(str(p["amount"])) for p in command.payments), Decimal("0")
        )
        if not sale.is_covered_by(total_payment):
            raise ValidationError(
                message="Payment amount is insufficient",
                detail=f"Total: {sale.total}, paid: {total_payment}",
            )

        # 8. Confirmar venta
        sale.confirm()
        self.sale_repo.update(sale)

        # 9. Crear movimientos de inventario
        for item in created_items:
            movement = Movement(
                product_id=item.product_id,
                quantity=-abs(item.quantity),
                type=MovementType.OUT,
                reason=f"Sale #{sale.id} confirmed",
            )
            self.movement_repo.create(movement)

            stock = self.stock_repo.first(product_id=item.product_id)
            if stock is None:
                raise InsufficientStockError(item.product_id, item.quantity, 0)
            stock.update_quantity(-abs(item.quantity))
            self.stock_repo.update(stock)

        # 10. Registrar pagos
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

        # 11. Actualizar estado de pago
        sale.update_payment_status(total_payment)
        self.sale_repo.update(sale)

        # 12. Publicar evento
        items_data = [
            {
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "discount": item.discount,
                "tax_code": item.tax_code,
                "tax_amount": item.tax_amount,
                "subtotal": item.subtotal,
            }
            for item in created_items
        ]

        payments_data = [
            {
                "method": p.payment_method,
                "amount": p.amount,
            }
            for p in created_payments
        ]

        self.event_publisher.publish(
            SaleConfirmed(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                items=items_data,
                subtotal=sale.subtotal,
                total_discount=sale.discount,
                total=sale.total,
                payments=payments_data,
                source="pos",
            )
        )

        # 13. Retornar venta completa
        result = sale.dict()
        result["items"] = [
            {**item.dict(), "subtotal": item.subtotal} for item in created_items
        ]
        result["payments"] = [p.dict() for p in created_payments]
        return result
