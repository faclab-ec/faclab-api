from src.shared.domain.exceptions import DomainError


class InvalidAdjustmentStatusError(DomainError):
    """La operación no está permitida en el estado actual del ajuste"""

    error_code = "INVALID_ADJUSTMENT_STATUS"

    def __init__(self, current_status: str, operation: str):
        self.current_status = current_status
        self.operation = operation
        super().__init__(
            message=f"No se puede {operation} un ajuste en estado {current_status}",
            detail=f"current_status={current_status}, operation={operation}",
        )
