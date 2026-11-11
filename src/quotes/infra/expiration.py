"""Marks EXPIRED the open quotes (draft, sent, accepted) whose validity ended
before today, of every tenant (S5.4), as faclab_worker. The worker runs it with
the purges; this command runs it once, by hand. Idempotent: a second pass finds
nothing.

Marking them is for the lists: a quote past its date is already treated as
expired (`Quote.is_expired`) and isn't converted until it is renewed.

Usage:
    python -m src.quotes.infra.expiration
"""

import sys
from datetime import date, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from src.quotes.domain.entities import OPEN_QUOTE_STATUSES, QuoteStatus
from src.quotes.infra.models import QuoteModel

logger = structlog.get_logger(__name__)


def expire_quotes(session_maker: sessionmaker[Session], today: date) -> int:
    """Marks them; returns how many"""
    with session_maker() as session, session.begin():
        result = session.execute(
            update(QuoteModel)
            .where(
                QuoteModel.status.in_([s.value for s in OPEN_QUOTE_STATUSES]),
                QuoteModel.valid_until < today,
            )
            .values(status=QuoteStatus.EXPIRED.value, updated_at=datetime.now())
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def expire() -> int:
    """The worker's task"""
    from src.shared.infra.database import worker_session_maker

    expired = expire_quotes(worker_session_maker(), date.today())
    # A pass that changed nothing only shows in DEBUG (OBSERVABILITY.md 4.5)
    (logger.info if expired else logger.debug)("quotes_expired", expired=expired)
    return expired


def main() -> int:
    expire()
    return 0


if __name__ == "__main__":
    sys.exit(main())
