"""
Event handlers that react to purchasing domain events.
"""

from typing import Any

import structlog

from src.inventory.movement.app.commands.movement import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.purchasing.domain.events import PurchaseOrderReceived
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)


@event_handler(PurchaseOrderReceived)
def handle_purchase_order_received(
    event: PurchaseOrderReceived, session: Any = None
) -> None:
    """
    When goods are received for a purchase order, create IN inventory movements.
    Each receipt item becomes an individual IN movement.
    """
    logger.info(
        "handling_purchase_order_received",
        purchase_order_id=event.purchase_order_id,
        order_number=event.order_number,
        is_complete=event.is_complete,
        item_count=len(event.items),
    )

    with create_sync_scope(session) as scope:
        try:
            for item in event.items:
                handler = scope.get(CreateMovementCommandHandler)

                command = CreateMovementCommand(
                    product_id=item["product_id"],
                    quantity=abs(item["quantity"]),
                    type=MovementType.IN.value,
                    location_id=item.get("location_id"),
                    reference_type="purchase_order",
                    reference_id=event.purchase_order_id,
                    reason=f"Purchase order {event.order_number} received",
                    # Recalculates the weighted average of the location (S5.6)
                    unit_cost=item.get("unit_cost"),
                )

                handler.handle(command)
                logger.info(
                    "in_movement_created",
                    purchase_order_id=event.purchase_order_id,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                )

        except Exception as e:
            logger.error(
                "purchase_order_received_handler_error",
                purchase_order_id=event.purchase_order_id,
                error=str(e),
            )
            raise
