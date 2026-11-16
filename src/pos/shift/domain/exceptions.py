"""Excepciones especificas del dominio de Shifts"""

from src.shared.domain.exceptions import AlreadyExistsError, DomainError


class ShiftError(DomainError):
    """Excepcion base para el dominio de shifts"""

    error_code = "SHIFT_ERROR"


class ShiftAlreadyOpenError(ShiftError):
    """Se lanza cuando se intenta abrir un turno y ya hay uno abierto"""

    error_code = "SHIFT_ALREADY_OPEN"

    def __init__(self):
        super().__init__(
            message="The terminal already has an open shift",
            detail="Only one shift can be open at a time in a terminal",
        )


class ShiftAlreadyClosedError(ShiftError):
    """Se lanza cuando se intenta cerrar un turno que ya esta cerrado"""

    error_code = "SHIFT_ALREADY_CLOSED"

    def __init__(self, shift_id: int):
        self.shift_id = shift_id
        super().__init__(
            message=f"Shift {shift_id} is already closed",
            detail=f"shift_id={shift_id}",
        )


class NoOpenShiftError(ShiftError):
    """Se lanza cuando se requiere un turno abierto y no hay ninguno"""

    error_code = "NO_OPEN_SHIFT"

    def __init__(self):
        super().__init__(
            message="No open shift found",
            detail="An open shift is required for this operation",
        )


class ClosingCountMissingError(ShiftError):
    """S5.9: el arqueo del cierre no cuenta un medio de pago que debe contarse:
    el efectivo siempre, y cada medio que tuvo movimiento en el turno"""

    error_code = "CLOSING_COUNT_MISSING"

    def __init__(self, methods: list[str]):
        self.methods = methods
        super().__init__(
            message="The closing count is missing payment methods: "
            + ", ".join(methods),
            detail="Count cash and every payment method the shift moved, except CREDIT",
        )


class ClosingCountInvalidError(ShiftError):
    """S5.9: el arqueo cuenta un medio que no admite (CREDIT, uno desconocido) o
    cuenta dos veces el mismo"""

    error_code = "CLOSING_COUNT_INVALID"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message=message, detail=detail)


class ClosingJustificationRequiredError(ShiftError):
    """S5.9: la diferencia de un medio supera el umbral y no trae justificación"""

    error_code = "CLOSING_JUSTIFICATION_REQUIRED"

    def __init__(self, methods: list[str], threshold: str):
        self.methods = methods
        super().__init__(
            message="A justification is required for the difference of: "
            + ", ".join(methods),
            detail=f"Differences over {threshold} must be justified",
        )


class ShiftClosingAlreadyExistsError(AlreadyExistsError):
    """S5.9: el turno ya tiene su cierre Z, o la terminal ya usó ese correlativo"""

    error_code = "SHIFT_CLOSING_ALREADY_EXISTS"

    def __init__(self):
        super().__init__(
            message="The shift already has its closing",
            detail="A shift is closed once and each Z number is used once",
        )
