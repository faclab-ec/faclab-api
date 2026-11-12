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
from src.purchasing.domain.events import PurchaseOrderReceived, SupplierReturnConfirmed
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


@event_handler(SupplierReturnConfirmed)
def handle_supplier_return_confirmed(
    event: SupplierReturnConfirmed, session: Any = None
) -> None:
    """Goods back to the supplier (S5.7): an OUT movement per line, at the
    location's average cost (S5.6), sorted by product and location so concurrent
    documents lock stock rows in the same order. Without enough available stock
    the whole return fails (INSUFFICIENT_STOCK)."""
    logger.info(
        "handling_supplier_return_confirmed",
        supplier_return_id=event.supplier_return_id,
        number=event.number,
        item_count=len(event.items),
    )
    lines = sorted(
        event.items, key=lambda i: (i["product_id"], i.get("location_id") or 0)
    )
    with create_sync_scope(session) as scope:
        handler = scope.get(CreateMovementCommandHandler)
        for item in lines:
            handler.handle(
                CreateMovementCommand(
                    product_id=item["product_id"],
                    quantity=-abs(item["quantity"]),
                    type=MovementType.OUT.value,
                    location_id=item.get("location_id"),
                    reference_type="supplier_return",
                    reference_id=event.supplier_return_id,
                    reason=f"Supplier return {event.number}",
                )
            )
