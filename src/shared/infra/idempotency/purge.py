"""Deletes the idempotency keys older than IDEMPOTENCY_KEY_RETENTION_HOURS, of
every tenant (as faclab_worker, which bypasses row-level security). The worker
runs it periodically (S3.4); this command runs it once, by hand.

Usage:
    python -m src.shared.infra.idempotency.purge
"""

import sys
from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.idempotency.models import IdempotencyKeyModel

logger = structlog.get_logger(__name__)


def purge_expired(session_maker: sessionmaker[Session], before: datetime) -> int:
    """Deletes the keys created before `before`; returns how many"""
    with session_maker() as session, session.begin():
        result = session.execute(
            delete(IdempotencyKeyModel)
            .where(IdempotencyKeyModel.created_at < before)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def purge() -> int:
    """The worker's task: purges with the configured retention"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    retention = timedelta(hours=config.IDEMPOTENCY_KEY_RETENTION_HOURS)
    deleted = purge_expired(worker_session_maker(), datetime.now() - retention)
    logger.info(
        "idempotency_keys_purged",
        deleted=deleted,
        retention_hours=config.IDEMPOTENCY_KEY_RETENTION_HOURS,
    )
    return deleted


def main() -> int:
    purge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
