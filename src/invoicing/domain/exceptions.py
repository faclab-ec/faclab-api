"""Excepciones de la integración con faclab-invoicing"""

from src.shared.domain.exceptions import ApplicationError


class InvoicingDisabledError(ApplicationError):
    """Se pidió facturar una venta pero la integración con Kafka está apagada"""

    error_code = "INVOICING_DISABLED"

    def __init__(self):
        super().__init__(
            message="Invoicing is disabled: KAFKA_ENABLED is false",
            detail="Sales are only sent to faclab-invoicing through Kafka",
        )
