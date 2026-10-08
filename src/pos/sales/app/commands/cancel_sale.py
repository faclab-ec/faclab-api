from dataclasses import dataclass

from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.app.repositories import StockRepository
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import SaleStatus
from src.sales.domain.events import SaleCancelled
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class POSCancelSaleCommand(Command):
    sale_id: int
    reason: str | None = None


@injectable(lifetime="scoped")
class POSCancelSaleCommandHandler(CommandHandler[POSCancelSaleCommand, dict]):
    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        movement_repo: MovementRepository,
        stock_repo: StockRepository,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.movement_repo = movement_repo
        self.stock_repo = stock_repo
        self.event_publisher = event_publisher

    def _handle(self, command: POSCancelSaleCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        was_confirmed = sale.status == SaleStatus.CONFIRMED
        items_data = []

        if was_confirmed:
            items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
            sale.cancel()
            self.sale_repo.update(sale)

            for item in items:
                movement = Movement(
                    product_id=item.product_id,
                    quantity=abs(item.quantity),
                    type=MovementType.IN,
                    reason=f"Sale #{command.sale_id} cancelled - reversal",
                )
                self.movement_repo.create(movement)

                stock = self.stock_repo.first(product_id=item.product_id)
                if stock:
                    stock.update_quantity(abs(item.quantity))
                    self.stock_repo.update(stock)

            items_data = [
                {"product_id": item.product_id, "quantity": item.quantity}
                for item in items
            ]
        else:
            sale.cancel()
            self.sale_repo.update(sale)

        self.event_publisher.publish(
            SaleCancelled(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                items=items_data,
                reason=command.reason or "",
                was_confirmed=was_confirmed,
                source="pos",
            )
        )

        return sale.dict()
