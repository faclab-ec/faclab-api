from dataclasses import dataclass

from wireup import injectable

from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.events import SaleItemRemoved
from src.sales.domain.exceptions import SaleItemNotInSaleError
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class RemoveSaleItemCommand(Command):
    """Comando para eliminar un item de una venta"""

    sale_id: int
    sale_item_id: int


@injectable(lifetime="scoped")
class RemoveSaleItemCommandHandler(CommandHandler[RemoveSaleItemCommand, dict]):
    """Handler para eliminar un item de una venta y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.event_publisher = event_publisher

    def _handle(self, command: RemoveSaleItemCommand) -> dict:
        """Elimina un item de la venta y recalcula los totales"""
        # Obtener la venta
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        # Validar que la venta esté en DRAFT
        sale.ensure_draft("remove items from")

        # Obtener el item
        sale_item = self.sale_item_repo.get_by_id(command.sale_item_id)
        if not sale_item:
            raise NotFoundError(f"Sale item with id {command.sale_item_id} not found")

        # Verificar que el item pertenece a la venta
        if sale_item.sale_id != command.sale_id:
            raise SaleItemNotInSaleError(command.sale_item_id, command.sale_id)

        # Guardar info del item para el evento
        item_dict = sale_item.dict()

        # Eliminar el item
        self.sale_item_repo.delete(sale_item.require_id())

        # Recalcular totales de la venta
        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        # Publicar evento
        self.event_publisher.publish(
            SaleItemRemoved(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                sale_item_id=sale_item.require_id(),
                product_id=sale_item.product_id,
                quantity=sale_item.quantity,
            )
        )

        return {"success": True, "removed_item": item_dict}
