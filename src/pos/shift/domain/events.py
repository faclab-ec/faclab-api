from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class ShiftOpened(DomainEvent):
    """Evento emitido cuando se abre un turno"""

    shift_id: int = 0
    terminal_id: int | None = None
    cashier_name: str = ""
    opening_balance: Decimal = Decimal("0")

    def _payload(self) -> dict[str, Any]:
        return {
            "shift_id": self.shift_id,
            "terminal_id": self.terminal_id,
            "cashier_name": self.cashier_name,
            "opening_balance": self.opening_balance,
        }


@dataclass
class ShiftClosed(DomainEvent):
    """Evento emitido cuando se cierra un turno"""

    shift_id: int = 0
    cashier_name: str = ""
    closing_balance: Decimal = Decimal("0")
    expected_balance: Decimal = Decimal("0")
    discrepancy: Decimal = Decimal("0")

    def _payload(self) -> dict[str, Any]:
        return {
            "shift_id": self.shift_id,
            "cashier_name": self.cashier_name,
            "closing_balance": self.closing_balance,
            "expected_balance": self.expected_balance,
            "discrepancy": self.discrepancy,
        }
