"""Eventos de la integración con faclab-invoicing"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class CreditNoteRequested(DomainEvent):
    """Una nota de crédito se pidió o se vuelve a pedir: su mensaje va al outbox
    en la misma transacción. Cada uno tiene su `event_id`, por el que
    faclab-invoicing deduplica."""

    credit_note_id: int = 0
    sale_id: int = 0

    def _payload(self) -> dict[str, Any]:
        return {"credit_note_id": self.credit_note_id, "sale_id": self.sale_id}


@dataclass
class CreditNoteAuthorized(DomainEvent):
    """El SRI autorizó una nota de crédito (S6.4: el webhook
    `credit_note.authorized`); un resultado repetido no lo publica"""

    credit_note_id: int = 0
    sale_id: int = 0
    refund_id: int | None = None
    # The invoice it modifies and itself, in faclab-invoicing
    invoice_id: str = ""
    document_id: str = ""
    number: str | None = None
    access_code: str | None = None
    authorized_at: datetime | None = None

    def _payload(self) -> dict[str, Any]:
        return {
            "credit_note_id": self.credit_note_id,
            "sale_id": self.sale_id,
            "refund_id": self.refund_id,
            "invoice_id": self.invoice_id,
            "document_id": self.document_id,
            "number": self.number,
            "access_code": self.access_code,
            "authorized_at": self.authorized_at,
        }
