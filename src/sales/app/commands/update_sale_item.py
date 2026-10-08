from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.exceptions import SaleItemNotInSaleError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateSaleItemCommand(Command):
    """Comando para actualizar un item de una venta"""

    sale_id: int
    sale_item_id: int
    quantity: int | None = None
    discount: Decimal | None = None


@injectable(lifetime="scoped")
class UpdateSaleItemCommandHandler(CommandHandler[UpdateSaleItemCommand, dict]):
    """Handler para actualizar un item de una venta y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo

    def _handle(self, command: UpdateSaleItemCommand) -> dict:
        """Actualiza un item de la venta y recalcula los totales"""
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        sale.ensure_draft("update items in")

        sale_item = self.sale_item_repo.get_by_id(command.sale_item_id)
        if not sale_item:
            raise NotFoundError(f"Sale item with id {command.sale_item_id} not found")

        if sale_item.sale_id != command.sale_id:
            raise SaleItemNotInSaleError(command.sale_item_id, command.sale_id)

        if command.quantity is not None:
            sale_item.quantity = command.quantity
        if command.discount is not None:
            sale_item.discount = command.discount

        sale_item.recalculate_tax()

        self.sale_item_repo.update(sale_item)

        # Recalcular totales de la venta
        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        result = sale_item.dict()
        result["subtotal"] = sale_item.subtotal
        return result
