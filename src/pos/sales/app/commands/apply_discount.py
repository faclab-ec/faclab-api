from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class ApplySaleDiscountCommand(Command):
    """Comando para aplicar descuento a nivel de venta"""

    sale_id: int
    discount_type: str
    discount_value: Decimal


@injectable(lifetime="scoped")
class ApplySaleDiscountCommandHandler(CommandHandler[ApplySaleDiscountCommand, dict]):
    """Handler para aplicar descuento a una venta y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo

    def _handle(self, command: ApplySaleDiscountCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        sale.apply_discount(command.discount_type, command.discount_value)

        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        return sale.dict()
