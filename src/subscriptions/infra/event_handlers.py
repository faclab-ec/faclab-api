"""The monthly count of electronic documents (S8.4): one more for each invoice
and credit note the SRI authorized, in the transaction that applies the
result. Their publishers pass their session."""

from typing import Any

from src.invoicing.domain.events import CreditNoteAuthorized
from src.sales.domain.events import SaleInvoiced
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.events.scope import create_sync_scope
from src.subscriptions.app.commands.usage import (
    CountDocumentCommand,
    CountDocumentCommandHandler,
    DocumentKind,
)


@event_handler(SaleInvoiced)
def count_invoice(event: SaleInvoiced, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        scope.get(CountDocumentCommandHandler).handle(
            CountDocumentCommand(DocumentKind.INVOICE, event.occurred_at)
        )


@event_handler(CreditNoteAuthorized)
def count_credit_note(event: CreditNoteAuthorized, session: Any = None) -> None:
    with create_sync_scope(session) as scope:
        scope.get(CountDocumentCommandHandler).handle(
            CountDocumentCommand(DocumentKind.CREDIT_NOTE, event.occurred_at)
        )
