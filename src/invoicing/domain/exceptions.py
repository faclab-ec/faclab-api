"""Excepciones de la integración con faclab-invoicing"""

from src.shared.domain.exceptions import ApplicationError, ConflictError


class InvoicingDisabledError(ApplicationError):
    """Se pidió facturar una venta pero la integración con Kafka está apagada"""

    error_code = "INVOICING_DISABLED"

    def __init__(self):
        super().__init__(
            message="Invoicing is disabled: KAFKA_ENABLED is false",
            detail="Sales are only sent to faclab-invoicing through Kafka",
        )


class DiscrepancyNotOpenError(ConflictError):
    """Solo se marca revisada una discrepancia abierta"""

    error_code = "INVOICE_DISCREPANCY_NOT_OPEN"

    def __init__(self, discrepancy_id: int | None, status: str):
        super().__init__(
            message=f"Invoice discrepancy {discrepancy_id} is {status}, not open",
            detail=f"status={status}",
        )
