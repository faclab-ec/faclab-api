from src.shared.domain.exceptions import AlreadyExistsError, DomainError


class SerialNumberAlreadyExistsError(AlreadyExistsError):
    error_code = "SERIAL_NUMBER_ALREADY_EXISTS"

    def __init__(self, serial_number: str | None = None):
        if serial_number is None:
            message = "Serial number already exists."
        else:
            message = f"Serial number '{serial_number}' already exists."
        super().__init__(message)


class InvalidSerialStatusError(DomainError):
    error_code = "INVALID_SERIAL_STATUS"

    def __init__(self, serial_number: str, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            message=(
                f"Cannot mark serial '{serial_number}' as {target_status}. "
                f"Current status: '{current_status}'."
            ),
            detail=f"current_status={current_status}, target_status={target_status}",
        )
