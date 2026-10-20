from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.pos.shift.domain.exceptions import ShiftAlreadyClosedError
from src.shared.domain.entities import Entity


class ShiftStatus(StrEnum):
    """Estado de un turno"""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Shift(Entity):
    """Turno de caja de una terminal. Una terminal tiene como máximo un turno
    abierto (índice único parcial). Los turnos anteriores a S2.6 no tienen
    terminal ni sucursal."""

    cashier_name: str
    terminal_id: int | None = None
    branch_id: int | None = None
    opened_by_user_id: int | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    opening_balance: Decimal = Decimal("0")
    closing_balance: Decimal | None = None
    expected_balance: Decimal | None = None
    discrepancy: Decimal | None = None
    status: ShiftStatus = ShiftStatus.OPEN
    notes: str | None = None
    closed_by: str | None = None
    id: int | None = None

    def __post_init__(self):
        if self.opened_at is None:
            self.opened_at = datetime.now()

    def close(
        self,
        closing_balance: Decimal,
        expected_balance: Decimal,
        closed_by: str | None = None,
    ) -> Decimal:
        """Cierra el turno y devuelve la discrepancia calculada"""
        if self.status != ShiftStatus.OPEN:
            raise ShiftAlreadyClosedError(self.require_id())
        self.status = ShiftStatus.CLOSED
        self.closed_at = datetime.now()
        self.closed_by = closed_by
        self.closing_balance = closing_balance
        self.expected_balance = expected_balance
        self.discrepancy = closing_balance - expected_balance
        return self.discrepancy
