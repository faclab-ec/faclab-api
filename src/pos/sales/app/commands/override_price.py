from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import Sale, SaleItem
from src.sales.domain.exceptions import SaleItemNotInSaleError
from src.shared.app.audit import AuditAction, AuditTrail
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
        audit: AuditTrail,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.audit = audit

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

        previous_price = item.unit_price
        item.unit_price = command.new_price
        item.price_override = command.new_price
        item.override_reason = command.reason
        item.recalculate_tax()

        self.sale_item_repo.update(item)

        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)
        audit_price_override(self.audit, sale, item, previous_price)

        result = item.dict()
        result["subtotal"] = item.subtotal
        return result


def audit_price_override(
    audit: AuditTrail, sale: Sale, item: SaleItem, previous_price: Decimal | None
) -> None:
    """A line sold at a price other than the product's, here or in a quick sale"""
    audit.record(
        AuditAction.SALE_PRICE_OVERRIDDEN,
        sale.require_id(),
        before={"unit_price": previous_price},
        after={
            "item_id": item.id,
            "product_id": item.product_id,
            "unit_price": item.unit_price,
            "reason": item.override_reason,
        },
        branch_id=sale.branch_id,
    )
