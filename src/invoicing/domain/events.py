"""Eventos de la integración con faclab-invoicing"""

from dataclasses import dataclass
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
