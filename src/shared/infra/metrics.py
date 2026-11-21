"""Business counters that only count what was committed (S7.1).

A sale is confirmed when its transaction commits, not when `SaleConfirmed` is
published: a handler that runs after it (invoicing, the receivable) can still
fail the request and roll everything back. `add_on_commit` keeps the
measurement in the session and records it after the commit; a transaction that
ends without committing (rollback, close) drops it. The listeners are
registered on every session maker (`create_session_maker`).
"""

from collections.abc import Mapping

from opentelemetry.metrics import Counter
from sqlalchemy.orm import Session, SessionTransaction

_PENDING = "faclab.metrics.pending"


def add_on_commit(
    session: Session | None,
    counter: Counter,
    attributes: Mapping[str, str],
    amount: int = 1,
) -> None:
    """Count once the session commits. Without a session (an event published
    without it: its handler commits apart) it counts now."""
    if session is None:
        counter.add(amount, dict(attributes))
        return
    session.info.setdefault(_PENDING, []).append((counter, amount, dict(attributes)))


def record_pending_metrics(session: Session) -> None:
    """after_commit: the transaction's measurements happened"""
    for counter, amount, attributes in session.info.pop(_PENDING, []):
        counter.add(amount, attributes)


def discard_pending_metrics(session: Session, transaction: SessionTransaction) -> None:
    """after_transaction_end: after a commit there is nothing left; after a
    rollback or a close what the transaction counted never happened"""
    if transaction.parent is None:
        session.info.pop(_PENDING, None)
