"""Lo que el core guarda de sus documentos en faclab-invoicing.

Conciliación (S4.3): una discrepancia es una venta que necesita que alguien la
mire: su factura no tuvo resultado a tiempo, o el SRI autorizó la factura de una
venta anulada.

Nota de crédito (S4.5): lo que se pidió acreditar y su resultado. La emite
faclab-invoicing; su comprador, número y fecha salen de la factura que modifica.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from src.invoicing.domain.exceptions import (
    CreditNoteAlreadyAuthorizedError,
    DiscrepancyNotOpenError,
)
from src.shared.domain.entities import Entity


class DiscrepancyKind(StrEnum):
    """Qué no cuadra entre la venta y faclab-invoicing"""

    # Confirmada y sin resultado de facturación después del umbral: pendiente
    # desde que se envió, o nunca enviada (Kafka apagado al confirmarla)
    CONFIRMED_WITHOUT_RESULT = "confirmed_without_result"
    # El SRI autorizó la factura de una venta que ya estaba anulada
    AUTHORIZED_ON_CANCELLED = "authorized_on_cancelled"


class DiscrepancyStatus(StrEnum):
    """`open` hasta que un usuario la marca revisada (`reviewed`) o la condición
    desaparece sola (`resolved`)"""

    OPEN = "open"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


@dataclass
class InvoiceDiscrepancy(Entity):
    sale_id: int
    kind: DiscrepancyKind
    status: DiscrepancyStatus = DiscrepancyStatus.OPEN
    # The invoice faclab-invoicing reported, when there is one
    invoice_id: str | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by_id: int | None = None
    reviewed_by_name: str | None = None
    review_note: str | None = None
    id: int | None = None

    def review(
        self, user_id: int | None, user_name: str | None, note: str | None = None
    ) -> None:
        """Un usuario la vio y se hace cargo; solo una abierta"""
        if self.status != DiscrepancyStatus.OPEN:
            raise DiscrepancyNotOpenError(self.id, self.status)
        self.status = DiscrepancyStatus.REVIEWED
        self.reviewed_at = datetime.now()
        self.reviewed_by_id = user_id
        self.reviewed_by_name = user_name
        self.review_note = note

    def resolve(self) -> None:
        """La condición desapareció (la venta se reenvió, tuvo resultado o se
        anuló): sale de la lista, revisada o no"""
        if self.status == DiscrepancyStatus.RESOLVED:
            return
        self.status = DiscrepancyStatus.RESOLVED
        self.resolved_at = datetime.now()


class CreditNoteStatus(StrEnum):
    """PENDING desde que se pide, hasta que faclab-invoicing dice qué respondió
    el SRI"""

    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


@dataclass
class CreditNote(Entity):
    """Una nota de crédito pedida a faclab-invoicing: por una devolución de una
    venta facturada o, sin devolución, por la factura autorizada de una venta
    anulada"""

    sale_id: int
    # The invoice it modifies, in faclab-invoicing
    invoice_id: str
    reason: str
    refund_id: int | None = None
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    status: CreditNoteStatus = CreditNoteStatus.PENDING
    # The last document with a result: its XML and RIDE are downloaded with it
    document_id: str | None = None
    number: str | None = None
    access_code: str | None = None
    authorized_at: datetime | None = None
    rejection_reason: str | None = None
    # When it was last sent to faclab-invoicing
    requested_at: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None

    def authorize(
        self,
        document_id: str,
        number: str | None,
        access_code: str | None,
        authorized_at: datetime | None,
    ) -> bool:
        """El SRI la autorizó, también si un rechazo llegó antes; un resultado
        repetido no cambia nada. Dice si cambió."""
        if self.status == CreditNoteStatus.AUTHORIZED:
            return False
        self.status = CreditNoteStatus.AUTHORIZED
        self.document_id = document_id
        self.number = number
        self.access_code = access_code
        self.authorized_at = authorized_at
        self.rejection_reason = None
        return True

    def reject(
        self,
        document_id: str,
        reason: str | None,
        number: str | None = None,
        access_code: str | None = None,
    ) -> bool:
        """El SRI (o faclab-invoicing) la rechazó: se puede volver a pedir. Solo
        cambia una pendiente, y no por un rechazo del documento que ya se rechazó
        (un mensaje repetido que llega después de pedirla otra vez). Dice si
        cambió."""
        if self.status != CreditNoteStatus.PENDING:
            return False
        if document_id == self.document_id:
            return False
        self.status = CreditNoteStatus.REJECTED
        self.document_id = document_id
        self.number = number
        self.access_code = access_code
        self.rejection_reason = reason[:1000] if reason else None
        return True

    def request_again(self) -> None:
        """Vuelve a pedirse: si no se perdió, faclab-invoicing no emite otra"""
        if self.status == CreditNoteStatus.AUTHORIZED:
            raise CreditNoteAlreadyAuthorizedError(self.id)
        self.status = CreditNoteStatus.PENDING
        self.rejection_reason = None
        self.requested_at = datetime.now()
