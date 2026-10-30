"""Conciliación entre las ventas y sus facturas en faclab-invoicing (S4.3).

Una discrepancia es una venta que necesita que alguien la mire: su factura no
tuvo resultado a tiempo, o el SRI autorizó la factura de una venta anulada.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.invoicing.domain.exceptions import DiscrepancyNotOpenError
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
