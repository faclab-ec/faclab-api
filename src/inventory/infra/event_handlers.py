"""
Event handlers que reaccionan a eventos de otros módulos.
Estos handlers permiten el desacoplamiento entre módulos vía eventos.
"""

from typing import Any

import structlog

from src.inventory.movement.app.commands import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.sales.domain.events import SaleCancelled, SaleConfirmed
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)


@event_handler(SaleConfirmed)
def handle_sale_confirmed(event: SaleConfirmed, session: Any = None) -> None:
    """
    Cuando se confirma una venta, crear movimientos OUT de inventario.
    Este handler desacopla el módulo de sales del módulo de inventory.
    """
    if event.source == "pos":
        logger.info(
            "skip_inventory_from_pos",
            sale_id=event.sale_id,
            reason="pos_handles_inventory_atomically",
        )
        return

    logger.info("handling_sale_confirmed", sale_id=event.sale_id)

    with create_sync_scope(session) as scope:
        try:
            for item in event.items:
                handler = scope.get(CreateMovementCommandHandler)

                # In base units (S5.2): a line of 2 boxes of 100 takes 200
                command = CreateMovementCommand(
                    product_id=item["product_id"],
                    quantity=-abs(item.get("base_quantity", item["quantity"])),
                    type=MovementType.OUT.value,
                    reason=f"Sale #{event.sale_id} confirmed",
                )

                handler.handle(command)
                logger.info(
                    "out_movement_created",
                    sale_id=event.sale_id,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                )

        except Exception as e:
            logger.error(
                "sale_confirmed_handler_error",
                sale_id=event.sale_id,
                error=str(e),
            )
            raise


@event_handler(SaleCancelled)
def handle_sale_cancelled(event: SaleCancelled, session: Any = None) -> None:
    """
    Cuando se cancela una venta, revertir movimientos si la venta estaba confirmada.
    Solo crea movimientos IN si was_confirmed=True.
    """
    if event.source == "pos":
        logger.info(
            "skip_inventory_from_pos",
            sale_id=event.sale_id,
            reason="pos_handles_inventory_atomically",
        )
        return

    logger.info(
        "handling_sale_cancelled",
        sale_id=event.sale_id,
        was_confirmed=event.was_confirmed,
    )

    if not event.was_confirmed:
        logger.info(
            "skip_inventory_reversal",
            sale_id=event.sale_id,
            reason="sale_was_not_confirmed",
        )
        return

    with create_sync_scope(session) as scope:
        try:
            for item in event.items:
                handler = scope.get(CreateMovementCommandHandler)

                command = CreateMovementCommand(
                    product_id=item["product_id"],
                    quantity=abs(item["quantity"]),
                    type=MovementType.IN.value,
                    reason=f"Sale #{event.sale_id} cancelled - reversal",
                )

                handler.handle(command)
                logger.info(
                    "in_reversal_movement_created",
                    sale_id=event.sale_id,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
                )

        except Exception as e:
            logger.error(
                "sale_cancelled_handler_error",
                sale_id=event.sale_id,
                error=str(e),
            )
            raise
