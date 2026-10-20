"""Excepciones especificas del dominio de Shifts"""

from src.shared.domain.exceptions import DomainError


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
