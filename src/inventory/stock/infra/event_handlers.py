"""
Event handlers para Stock que reaccionan a eventos de otros módulos.
Este handler desacopla Movement de Stock mediante eventos.
"""

from typing import Any

import structlog

from src.inventory.movement.domain.events import MovementCreated
from src.inventory.stock.app.repositories import StockRepository
from src.inventory.stock.domain.entities import Stock
from src.inventory.stock.domain.events import StockCreated, StockUpdated
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.event_bus import EventBus
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)


@event_handler(MovementCreated)
def handle_movement_created(event: MovementCreated, session: Any = None) -> None:
    """
    Cuando se crea un movimiento, actualizar o crear el stock correspondiente.
    El stock se maneja por (product_id, location_id). Si location_id es None,
    se actualiza el stock sin ubicación asignada.
    """
    logger.info(
        "handling_movement_created",
        movement_id=event.aggregate_id,
        product_id=event.product_id,
        quantity=event.quantity,
        location_id=event.location_id,
    )

    with create_sync_scope(session) as scope:
        try:
            stock_repo = scope.get(StockRepository)

            # Find stock by (product_id, location_id)
            if event.location_id is not None:
                stock = stock_repo.first(
                    product_id=event.product_id, location_id=event.location_id
                )
            else:
                stock = stock_repo.first(product_id=event.product_id, location_id=None)

            if stock is None:
                logger.info(
                    "creating_new_stock",
                    product_id=event.product_id,
                    location_id=event.location_id,
                )
                stock = Stock(
                    product_id=event.product_id,
                    quantity=event.quantity,
                    location_id=event.location_id,
                )
                stock = stock_repo.create(stock)

                EventBus.publish(
                    StockCreated(
                        aggregate_id=stock.require_id(),
                        product_id=stock.product_id,
                        quantity=stock.quantity,
                        location_id=stock.location_id,
                    ),
                    session=session,
                )
                logger.info(
                    "stock_created",
                    stock_id=stock.id,
                    product_id=stock.product_id,
                    quantity=stock.quantity,
                    location_id=stock.location_id,
                )
            else:
                old_quantity = stock.quantity
                logger.info(
                    "updating_existing_stock",
                    stock_id=stock.id,
                    current_quantity=old_quantity,
                    delta=event.quantity,
                    location_id=stock.location_id,
                )

                stock.update_quantity(event.quantity)
                stock = stock_repo.update(stock)

                EventBus.publish(
                    StockUpdated(
                        aggregate_id=stock.require_id(),
                        product_id=stock.product_id,
                        old_quantity=old_quantity,
                        new_quantity=stock.quantity,
                        location_id=stock.location_id,
                    ),
                    session=session,
                )
                logger.info(
                    "stock_updated",
                    stock_id=stock.id,
                    old_quantity=old_quantity,
                    new_quantity=stock.quantity,
                    location_id=stock.location_id,
                )

        except Exception as e:
            logger.error(
                "movement_created_handler_error",
                movement_id=event.aggregate_id,
                product_id=event.product_id,
                error=str(e),
            )
            raise
