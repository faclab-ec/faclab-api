from abc import ABC, abstractmethod

from src.pos.shift.domain.closing import ShiftTotals


class ShiftTotalsReader(ABC):
    """Lee lo que un turno movió (S5.9): un solo lugar para el reporte X, el
    resumen de caja, el arqueo y el cierre Z, que así salen de los mismos
    números. Solo cuentan las filas del tenant del contexto."""

    @abstractmethod
    def of_shift(self, shift_id: int) -> ShiftTotals:
        raise NotImplementedError
