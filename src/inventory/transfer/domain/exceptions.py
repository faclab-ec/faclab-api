from src.shared.domain.exceptions import DomainError, ValidationError


class InvalidTransferStatusError(DomainError):
    """La operación no está permitida en el estado actual de la transferencia"""

    error_code = "INVALID_TRANSFER_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"No se puede {operation} una transferencia en estado {current_status}",
            detail=f"current_status={current_status}, operation={operation}",
        )


class SameLocationTransferError(ValidationError):
    def __init__(self):
        super().__init__("La ubicación de origen y destino no pueden ser la misma")


class TransferHasNoItemsError(DomainError):
    error_code = "TRANSFER_HAS_NO_ITEMS"

    def __init__(self, transfer_id: int | None):
        super().__init__(
            message="La transferencia no tiene ítems",
            detail=f"transfer_id={transfer_id}",
        )
