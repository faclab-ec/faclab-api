"""Inventory metrics (S7.1): movements written and stock rejections.

`faclab.movement.source` is the document that moved the stock (its
`reference_type`), `manual` without one and `other` for any type outside this
list, so the attribute stays bounded whatever document appears later.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.shared.domain.exceptions import BaseError
from src.shared.infra.metrics import add_on_commit
from src.shared.infra.telemetry_instruments import inventory_movements, stock_rejections

MOVEMENT_SOURCES = frozenset(
    {"sale", "refund", "purchase_order", "supplier_return", "adjustment", "transfer"}
)
INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"


def movement_source(reference_type: str | None) -> str:
    if reference_type is None:
        return "manual"
    return reference_type if reference_type in MOVEMENT_SOURCES else "other"


def count_movement(session: Session, movement: Movement) -> None:
    """A movement written, counted once its transaction commits"""
    add_on_commit(
        session,
        inventory_movements,
        {
            "faclab.movement.type": MovementType(movement.type).value.lower(),
            "faclab.movement.source": movement_source(movement.reference_type),
        },
    )


def count_stock_rejection(reference_type: str | None) -> None:
    """An attempt to take stock that isn't available, by the document that
    tried (its reference type): counted now, its transaction rolls back"""
    stock_rejections.add(1, {"faclab.movement.source": movement_source(reference_type)})


@contextmanager
def stock_attempt(source: str) -> Generator[None]:
    """Counts the INSUFFICIENT_STOCK of an operation that takes stock without
    writing a movement (the reservation of a transfer)"""
    try:
        yield
    except BaseError as exc:
        if exc.error_code == INSUFFICIENT_STOCK:
            count_stock_rejection(source)
        raise
