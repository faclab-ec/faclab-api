"""Deletes the login sessions revoked or expired more than
AUTH_SESSION_RETENTION_DAYS ago, of every tenant (as faclab_worker). A refresh
token of a deleted session is rejected like one of a revoked session. The
worker runs it periodically."""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, or_
from sqlalchemy.orm import Session, sessionmaker

from src.auth.infra.models import AuthSessionModel

logger = structlog.get_logger(__name__)


def purge_finished(session_maker: sessionmaker[Session], before: datetime) -> int:
    """Deletes the sessions revoked or expired before `before`; returns how many"""
    with session_maker() as session, session.begin():
        result = session.execute(
            delete(AuthSessionModel)
            .where(
                or_(
                    AuthSessionModel.revoked_at < before,
                    AuthSessionModel.expires_at < before,
                )
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount


def purge() -> int:
    """The worker's task: purges with the configured retention"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    retention = timedelta(days=config.AUTH_SESSION_RETENTION_DAYS)
    deleted = purge_finished(worker_session_maker(), datetime.now() - retention)
    logger.info(
        "auth_sessions_purged",
        deleted=deleted,
        retention_days=config.AUTH_SESSION_RETENTION_DAYS,
    )
    return deleted
