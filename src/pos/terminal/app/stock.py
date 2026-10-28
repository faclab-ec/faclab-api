from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from wireup import injectable

from src.inventory.movement.app.repositories import MovementRepository
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.inventory.stock.app.repositories import StockRepository
from src.inventory.stock.domain.entities import Stock
from src.sales.domain.exceptions import InsufficientStockError


class StockLine(Protocol):
    """A sale or refund item: what moves and how much"""

    product_id: int
    quantity: int


@injectable(lifetime="scoped")
class TerminalStock:
    """The stock effects of the POS, written in the request's transaction: a
    sale takes from its terminal's location, a cancellation or refund puts back.

    Every product locks its stock row (`first_for_update`), sorted by product
    so concurrent requests lock in the same order and can't deadlock. Each
    movement points at its document (`reference_type`, `reference_id`)."""

    def __init__(self, stock_repo: StockRepository, movement_repo: MovementRepository):
        self.stock_repo = stock_repo
        self.movement_repo = movement_repo

    def take(
        self,
        lines: Iterable[StockLine],
        location_id: int | None,
        reason: str,
        reference_type: str,
        reference_id: int,
    ) -> None:
        """OUT movements from the location; fails if what it has available
        (not reserved for a transfer) doesn't cover the lines of a product
        together, whatever other locations hold"""
        by_product: dict[int, list[StockLine]] = defaultdict(list)
        for line in lines:
            by_product[line.product_id].append(line)

        for product_id in sorted(by_product):
            product_lines = by_product[product_id]
            total = sum(abs(line.quantity) for line in product_lines)
            stock = self.stock_repo.first_for_update(
                product_id=product_id, location_id=location_id
            )
            available = stock.available_quantity if stock else 0
            if stock is None or available < total:
                raise InsufficientStockError(product_id, total, available)
            for line in product_lines:
                self.movement_repo.create(
                    Movement(
                        product_id=product_id,
                        quantity=-abs(line.quantity),
                        type=MovementType.OUT,
                        location_id=location_id,
                        reference_type=reference_type,
                        reference_id=reference_id,
                        reason=reason,
                    )
                )
            stock.update_quantity(-total)
            self.stock_repo.update(stock)

    def put_back(
        self,
        lines: Iterable[StockLine],
        location_id: int | None,
        reason: str,
        reference_type: str,
        reference_id: int,
    ) -> None:
        """IN movements into the location, creating its stock row if needed"""
        for line in sorted(lines, key=lambda line: line.product_id):
            self.movement_repo.create(
                Movement(
                    product_id=line.product_id,
                    quantity=abs(line.quantity),
                    type=MovementType.IN,
                    location_id=location_id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    reason=reason,
                )
            )
            stock = self.stock_repo.first_for_update(
                product_id=line.product_id, location_id=location_id
            )
            if stock is None:
                self.stock_repo.create(
                    Stock(
                        product_id=line.product_id,
                        quantity=abs(line.quantity),
                        location_id=location_id,
                    )
                )
            else:
                stock.update_quantity(abs(line.quantity))
                self.stock_repo.update(stock)

    def taken_from(self, reference_type: str, reference_id: int) -> int | None:
        """The location a document's OUT movements took from (None if it has
        none, e.g. a sale confirmed before S2.6)"""
        for movement in self.movement_repo.filter_by(
            reference_type=reference_type, reference_id=reference_id
        ):
            if movement.type == MovementType.OUT:
                return movement.location_id
        return None
