"""
Event handlers for Lot that react to purchasing domain events.
Creates or updates lots when purchase orders are received.
"""

from typing import Any

import structlog

# The lot handler links each lot to the IN movement created by purchasing's
# PurchaseOrderReceived handler, so that handler must be subscribed first.
# EventBus runs handlers in subscription order, and importing the module
# subscribes it.
import src.purchasing.infra.event_handlers  # noqa: F401
from src.purchasing.domain.events import PurchaseOrderReceived
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)


@event_handler(PurchaseOrderReceived)
def handle_purchase_order_received_lots(
    event: PurchaseOrderReceived, session: Any = None
) -> None:
    """
    When goods are received for a purchase order, create or update lots.
    Only processes items that include a lot_number.
    """
    items_with_lots = [item for item in event.items if item.get("lot_number")]
    if not items_with_lots:
        return

    logger.info(
        "handling_purchase_order_received_lots",
        purchase_order_id=event.purchase_order_id,
        items_with_lots=len(items_with_lots),
    )

    with create_sync_scope(session) as scope:
        try:
            from src.inventory.lot.app.repositories import (
                LotRepository,
                MovementLotItemRepository,
            )
            from src.inventory.lot.domain.entities import Lot, MovementLotItem
            from src.inventory.movement.app.repositories import MovementRepository

            lot_repo = scope.get(LotRepository)
            movement_lot_item_repo = scope.get(MovementLotItemRepository)
            movement_repo = scope.get(MovementRepository)

            used_movement_ids: set[int] = set()

            for item in items_with_lots:
                product_id = item["product_id"]
                lot_number = item["lot_number"]
                quantity = item["quantity"]

                # Find existing lot or create new one
                existing_lot = lot_repo.first(
                    product_id=product_id, lot_number=lot_number
                )

                if existing_lot is None:
                    lot = Lot(
                        product_id=product_id,
                        lot_number=lot_number,
                        initial_quantity=quantity,
                        current_quantity=quantity,
                    )
                    lot = lot_repo.create(lot)
                    logger.info(
                        "lot_created",
                        lot_id=lot.id,
                        product_id=product_id,
                        lot_number=lot_number,
                        quantity=quantity,
                    )
                else:
                    existing_lot.receive(quantity)
                    lot = lot_repo.update(existing_lot)
                    logger.info(
                        "lot_updated",
                        lot_id=lot.id,
                        product_id=product_id,
                        lot_number=lot_number,
                        new_quantity=lot.current_quantity,
                    )

                # Find the movement created for this item and link it. Earlier
                # partial receipts of the same order can match too; the purchasing
                # handler created one movement per event item, in order, so this
                # receipt's movements are the newest ones for the same item key.
                same_key_items = sum(
                    1
                    for i in event.items
                    if i["product_id"] == product_id and i["quantity"] == quantity
                )
                movements = sorted(
                    movement_repo.filter_by(
                        reference_type="purchase_order",
                        reference_id=event.purchase_order_id,
                        product_id=product_id,
                        quantity=quantity,
                    ),
                    key=lambda m: m.require_id(),
                )[-same_key_items:]
                movement = next(
                    (m for m in movements if m.id not in used_movement_ids),
                    None,
                )
                if movement is not None:
                    used_movement_ids.add(movement.require_id())
                    movement_lot_item = MovementLotItem(
                        movement_id=movement.require_id(),
                        lot_id=lot.require_id(),
                        quantity=quantity,
                    )
                    movement_lot_item_repo.create(movement_lot_item)
                    logger.info(
                        "movement_lot_item_created",
                        movement_id=movement.id,
                        lot_id=lot.id,
                        quantity=quantity,
                    )

        except Exception as e:
            logger.error(
                "purchase_order_received_lots_handler_error",
                purchase_order_id=event.purchase_order_id,
                error=str(e),
            )
            raise
