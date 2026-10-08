from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.refund.app.repositories import RefundItemRepository, RefundRepository
from src.pos.refund.domain.entities import Refund, RefundItem, RefundStatus
from src.pos.refund.domain.exceptions import (
    ExceedsOriginalQuantityError,
    RefundItemNotInSaleError,
    SaleNotConfirmedError,
)
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.exceptions import NoOpenShiftError
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import SaleStatus
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateRefundCommand(Command):
    original_sale_id: int
    items: list[dict]
    reason: str | None = None
    refunded_by: str | None = None


@injectable(lifetime="scoped")
class CreateRefundCommandHandler(CommandHandler[CreateRefundCommand, dict]):
    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        refund_repo: RefundRepository,
        refund_item_repo: RefundItemRepository,
        shift_repo: ShiftRepository,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.refund_repo = refund_repo
        self.refund_item_repo = refund_item_repo
        self.shift_repo = shift_repo

    def _handle(self, command: CreateRefundCommand) -> dict:
        sale = self.sale_repo.get_by_id(command.original_sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.original_sale_id} not found")

        if sale.status != SaleStatus.CONFIRMED:
            raise SaleNotConfirmedError(command.original_sale_id)

        shift = self.shift_repo.first(status="OPEN")
        if shift is None:
            raise NoOpenShiftError()

        sale_items = self.sale_item_repo.filter_by(sale_id=command.original_sale_id)
        sale_item_lookup = {item.id: item for item in sale_items}

        previous_refunds = self.refund_repo.filter_by(
            original_sale_id=command.original_sale_id
        )
        already_refunded: dict[int, int] = {}
        for prev_refund in previous_refunds:
            if prev_refund.status == RefundStatus.CANCELLED:
                continue
            prev_items = self.refund_item_repo.filter_by(refund_id=prev_refund.id)
            for prev_item in prev_items:
                already_refunded[prev_item.original_sale_item_id] = (
                    already_refunded.get(prev_item.original_sale_item_id, 0)
                    + prev_item.quantity
                )

        for item_data in command.items:
            sale_item_id = item_data["sale_item_id"]
            if sale_item_id not in sale_item_lookup:
                raise RefundItemNotInSaleError(sale_item_id, command.original_sale_id)

            original_item = sale_item_lookup[sale_item_id]
            requested_qty = item_data["quantity"]
            already_qty = already_refunded.get(sale_item_id, 0)
            remaining = original_item.quantity - already_qty

            if requested_qty > remaining:
                raise ExceedsOriginalQuantityError(
                    sale_item_id, requested_qty, remaining
                )

        refund = Refund(
            original_sale_id=command.original_sale_id,
            shift_id=shift.id,
            reason=command.reason,
            refunded_by=command.refunded_by,
        )
        refund = self.refund_repo.create(refund)

        created_items = []
        for item_data in command.items:
            sale_item = sale_item_lookup[item_data["sale_item_id"]]
            quantity = item_data["quantity"]

            item_subtotal = sale_item.unit_price * quantity
            discount_amount = item_subtotal * (sale_item.discount / Decimal("100"))
            item_subtotal = item_subtotal - discount_amount
            tax_amount = item_subtotal * sale_item.tax_code.rate / Decimal("100")

            refund_item = RefundItem(
                refund_id=refund.id,
                original_sale_item_id=sale_item.id,
                product_id=sale_item.product_id,
                quantity=quantity,
                unit_price=sale_item.unit_price,
                discount=sale_item.discount,
                tax_code=sale_item.tax_code,
                tax_amount=tax_amount,
            )
            refund_item = self.refund_item_repo.create(refund_item)
            created_items.append(refund_item)

        subtotal = sum(item.subtotal for item in created_items)
        tax = sum(item.tax_amount for item in created_items)
        refund.subtotal = subtotal
        refund.tax = tax
        refund.total = subtotal + tax
        self.refund_repo.update(refund)

        result = refund.dict()
        result["items"] = [
            {**item.dict(), "subtotal": item.subtotal} for item in created_items
        ]
        return result
