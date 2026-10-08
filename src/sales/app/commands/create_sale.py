from dataclasses import dataclass

from wireup import injectable

from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import Sale
from src.sales.domain.events import SaleCreated
from src.sales.domain.exceptions import CustomerRequiredError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class CreateSaleCommand(Command):
    """Comando para crear una nueva venta"""

    customer_id: int | None = None
    is_final_consumer: bool = False
    shift_id: int | None = None
    notes: str | None = None
    created_by: str | None = None


@injectable(lifetime="scoped")
class CreateSaleCommandHandler(CommandHandler[CreateSaleCommand, dict]):
    """Handler para crear una nueva venta en estado DRAFT"""

    def __init__(self, repo: SaleRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CreateSaleCommand) -> dict:
        """Crea una nueva venta en estado DRAFT"""
        customer_id = command.customer_id
        if command.is_final_consumer:
            customer_id = None
        elif customer_id is None:
            raise CustomerRequiredError()

        sale = Sale(
            customer_id=customer_id,
            is_final_consumer=command.is_final_consumer,
            shift_id=command.shift_id,
            notes=command.notes,
            created_by=command.created_by,
        )

        sale = self.repo.create(sale)

        # Publicar evento
        self.event_publisher.publish(
            SaleCreated(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                customer_id=sale.customer_id,
                total=sale.total,
            )
        )

        return sale.dict()
