"""In-memory doubles of the Z closings and of a shift's totals (S5.9)"""

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from src.pos.shift.app.repositories import ShiftClosingRepository
from src.pos.shift.app.totals import ShiftTotalsReader
from src.pos.shift.domain.closing import ShiftClosing, ShiftClosingLine, ShiftTotals
from src.pos.shift.domain.exceptions import ShiftClosingAlreadyExistsError
from src.sales.domain.entities import PaymentMethod


class InMemoryShiftClosings(ShiftClosingRepository):
    def __init__(self, closings: Iterable[ShiftClosing] = ()):
        self.closings: list[ShiftClosing] = list(closings)

    def add(self, closing: ShiftClosing) -> ShiftClosing:
        taken = any(
            c.shift_id == closing.shift_id
            or (c.terminal_id, c.sequence) == (closing.terminal_id, closing.sequence)
            for c in self.closings
        )
        if taken:
            raise ShiftClosingAlreadyExistsError()
        saved = replace(closing, id=len(self.closings) + 1)
        self.closings.append(saved)
        return saved

    def of_shift(self, shift_id: int) -> ShiftClosing | None:
        return next((c for c in self.closings if c.shift_id == shift_id), None)

    def numbers_of(self, shift_ids: Iterable[int]) -> dict[int, str]:
        ids = set(shift_ids)
        return {c.shift_id: c.number for c in self.closings if c.shift_id in ids}

    def next_sequence(self, terminal_id: int | None) -> int:
        sequences = [c.sequence for c in self.closings if c.terminal_id == terminal_id]
        return max(sequences, default=0) + 1


class FakeShiftTotals(ShiftTotalsReader):
    """The same totals for any shift"""

    def __init__(self, totals: ShiftTotals | None = None):
        self.totals = totals or ShiftTotals()

    def of_shift(self, shift_id: int) -> ShiftTotals:
        return self.totals


def make_closing(**overrides) -> ShiftClosing:
    """A Z closing of shift 1 at terminal 3 with only its cash line"""
    defaults: dict = {
        "shift_id": 1,
        "sequence": 1,
        "number": "Z-001-CAJA-01-000001",
        "cashier_name": "Juan",
        "closed_at": datetime(2026, 3, 14, 18, 0),
        "terminal_id": 3,
        "branch_id": 1,
        "opened_at": datetime(2026, 3, 14, 8, 0),
        "opening_balance": Decimal("500.00"),
        "lines": [
            ShiftClosingLine(
                payment_method=PaymentMethod.CASH,
                expected=Decimal("500.00"),
                counted=Decimal("500.00"),
                difference=Decimal("0.00"),
            )
        ],
    }
    defaults.update(overrides)
    return ShiftClosing(**defaults)
