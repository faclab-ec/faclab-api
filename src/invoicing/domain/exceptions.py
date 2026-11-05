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


class CreditNotesDisabledError(ApplicationError):
    """Se pidió una nota de crédito con CREDIT_NOTES_ENABLED apagado"""

    error_code = "CREDIT_NOTES_DISABLED"

    def __init__(self):
        super().__init__(
            message="Credit notes are disabled: CREDIT_NOTES_ENABLED is false",
            detail="Turn it on to ask faclab-invoicing for credit notes",
        )


class CreditNoteAlreadyAuthorizedError(ConflictError):
    """Una nota autorizada no se vuelve a pedir"""

    error_code = "CREDIT_NOTE_ALREADY_AUTHORIZED"

    def __init__(self, credit_note_id: int | None):
        super().__init__(
            message=f"Credit note {credit_note_id} is already authorized",
            detail=f"credit_note_id={credit_note_id}",
        )


class CreditNoteAlreadyRequestedError(ConflictError):
    """La factura de la venta anulada ya tiene su nota: se vuelve a pedir esa"""

    error_code = "CREDIT_NOTE_ALREADY_REQUESTED"

    def __init__(self, sale_id: int):
        super().__init__(
            message=f"The cancelled sale {sale_id} already has a credit note",
            detail=f"sale_id={sale_id}",
        )


class CreditNoteNotApplicableError(ConflictError):
    """Solo una factura autorizada de una venta anulada se acredita por aquí"""

    error_code = "CREDIT_NOTE_NOT_APPLICABLE"

    def __init__(self, discrepancy_id: int, kind: str, status: str):
        super().__init__(
            message=(
                f"Invoice discrepancy {discrepancy_id} ({kind}, {status}) has no "
                "authorized invoice of a cancelled sale to credit"
            ),
            detail=f"kind={kind}, status={status}",
        )


class FinalConsumerCreditNoteError(ConflictError):
    """La factura a consumidor final no admite nota de crédito
    (NAC-DGERCGC25-00000014, art. 3, desde el 01/01/2026)"""

    error_code = "FINAL_CONSUMER_CREDIT_NOTE_NOT_ALLOWED"

    def __init__(self, sale_id: int):
        super().__init__(
            message=(
                f"The invoice of sale {sale_id} was issued to the final consumer: "
                "it doesn't admit a credit note"
            ),
            detail="NAC-DGERCGC25-00000014, art. 3",
        )
