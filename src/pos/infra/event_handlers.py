"""Sales metrics counted from their events (S7.1), once the transaction that
published them commits: a request that fails after `SaleConfirmed` (invoicing,
the receivable) never confirmed the sale. Every publisher passes its session."""

from typing import Any

from src.pos.refund.domain.events import RefundCompleted
from src.sales.domain.events import SaleCancelled, SaleConfirmed
from src.shared.infra.events.decorators import event_handler
from src.shared.infra.metrics import add_on_commit
from src.shared.infra.telemetry_instruments import (
    refunds_completed,
    sales_cancelled,
    sales_confirmed,
)

SOURCE = "faclab.sale.source"


@event_handler(SaleConfirmed)
def count_sale_confirmed(event: SaleConfirmed, session: Any = None) -> None:
    add_on_commit(session, sales_confirmed, {SOURCE: event.source})


@event_handler(SaleCancelled)
def count_sale_cancelled(event: SaleCancelled, session: Any = None) -> None:
    """Only a confirmed sale voided: discarding a draft is no cancellation"""
    if event.was_confirmed:
        add_on_commit(session, sales_cancelled, {SOURCE: event.source})


@event_handler(RefundCompleted)
def count_refund_completed(event: RefundCompleted, session: Any = None) -> None:
    add_on_commit(session, refunds_completed, {SOURCE: event.source})
