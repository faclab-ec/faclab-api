from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.exceptions import SaleItemNotInSaleError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class OverrideItemPriceCommand(Command):
    """Comando para sobreescribir el precio de un item de venta"""

    sale_id: int
    item_id: int
    new_price: Decimal
    reason: str


@injectable(lifetime="scoped")
class OverrideItemPriceCommandHandler(CommandHandler[OverrideItemPriceCommand, dict]):
    """Handler para sobreescribir el precio de un item y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo

    def _handle(self, command: OverrideItemPriceCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        sale.ensure_draft("override price in")

        if command.new_price <= Decimal("0"):
            raise ValidationError("new_price must be greater than 0")

        item = self.sale_item_repo.get_by_id(command.item_id)
        if not item:
            raise NotFoundError(f"Sale item with id {command.item_id} not found")

        if item.sale_id != command.sale_id:
            raise SaleItemNotInSaleError(command.item_id, command.sale_id)

        item.unit_price = command.new_price
        item.price_override = command.new_price
        item.override_reason = command.reason
        item.recalculate_tax()

        self.sale_item_repo.update(item)

        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        result = item.dict()
        result["subtotal"] = item.subtotal
        return result
