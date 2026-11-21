"""Gauges of the message queues, sampled by the worker (S7.1).

Every WORKER_METRICS_INTERVAL_SECONDS the `queue_metrics` task counts, as
faclab_worker (every tenant), the outbox messages still pending and failed per
topic, how old the oldest pending one is, and the dead letters the consumer
kept. The observable gauges export that sample until the next one; three
missed samples and the series stops instead of freezing.

Two aggregate queries per pass: the pending ones walk the partial indexes, the
failed ones the outbox, which the purge keeps at OUTBOX_RETENTION_DAYS. Topics
core writes or consumes report 0 when they have nothing, so a queue that empties
reads 0 rather than disappearing.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.kafka.models import DeadLetterModel, DeadLetterStatus
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus
from src.shared.infra.telemetry_instruments import (
    dead_letters_pending_values,
    outbox_failed_values,
    outbox_oldest_age_values,
    outbox_pending_values,
)

logger = structlog.get_logger(__name__)

TOPIC = "messaging.destination.name"


def outbox_by_topic(
    session_maker: sessionmaker[Session],
) -> tuple[dict[str, int], dict[str, int], dict[str, datetime]]:
    """Pending and failed messages per topic, and the oldest pending one"""
    statement = (
        select(
            OutboxMessageModel.topic,
            OutboxMessageModel.status,
            func.count(),
            func.min(OutboxMessageModel.created_at),
        )
        .where(
            OutboxMessageModel.status.in_(
                [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]
            )
        )
        .group_by(OutboxMessageModel.topic, OutboxMessageModel.status)
    )
    pending: dict[str, int] = {}
    failed: dict[str, int] = {}
    oldest: dict[str, datetime] = {}
    with session_maker() as session:
        for topic, status, count, created_at in session.execute(statement).tuples():
            if status == OutboxStatus.PENDING.value:
                pending[topic] = count
                oldest[topic] = created_at
            else:
                failed[topic] = count
    return pending, failed, oldest


def dead_letters_by_topic(session_maker: sessionmaker[Session]) -> dict[str, int]:
    """Dead letters still waiting to be processed again, per topic"""
    statement = (
        select(DeadLetterModel.topic, func.count())
        .where(DeadLetterModel.status == DeadLetterStatus.PENDING.value)
        .group_by(DeadLetterModel.topic)
    )
    with session_maker() as session:
        return dict(session.execute(statement).tuples().all())


def _points(
    values: Mapping[str, float], topics: Iterable[str]
) -> list[tuple[float, dict[str, str]]]:
    """A point per topic: the known ones with 0 when they have nothing"""
    every = dict.fromkeys(topics, 0.0) | dict(values)
    return [(float(every[topic]), {TOPIC: topic}) for topic in sorted(every)]


def sample_queues(
    session_maker: sessionmaker[Session],
    outbox_topics: Iterable[str],
    consumed_topics: Iterable[str],
    max_age: float,
    now: datetime | None = None,
) -> dict[str, dict[str, float]]:
    """One sample of every queue gauge; returns it by gauge and topic"""
    now = now or datetime.now()
    pending, failed, oldest = outbox_by_topic(session_maker)
    dead_letters = dead_letters_by_topic(session_maker)
    # created_at is written with the same naive clock (datetime.now)
    ages = {
        topic: max(0.0, (now - created_at).total_seconds())
        for topic, created_at in oldest.items()
    }
    outbox_topics = list(outbox_topics)
    gauges = {
        "outbox_pending": (outbox_pending_values, _points(pending, outbox_topics)),
        "outbox_failed": (outbox_failed_values, _points(failed, outbox_topics)),
        "outbox_oldest_age": (outbox_oldest_age_values, _points(ages, outbox_topics)),
        "dead_letters_pending": (
            dead_letters_pending_values,
            _points(dead_letters, consumed_topics),
        ),
    }
    for values, points in gauges.values():
        values.replace(points, max_age=max_age)
    return {
        name: {attrs[TOPIC]: value for value, attrs in points}
        for name, (_values, points) in gauges.items()
    }


def sample() -> dict[str, dict[str, float]]:
    """The worker's task: every topic core writes to the outbox or consumes"""
    from config import config
    from src.background.messaging import CONSUMER_HANDLERS
    from src.invoicing.infra.event_handlers import (
        CREDIT_NOTES_REQUESTED_TOPIC,
        SALES_CONFIRMED_TOPIC,
    )
    from src.shared.infra.database import worker_session_maker

    result = sample_queues(
        worker_session_maker(),
        outbox_topics=(SALES_CONFIRMED_TOPIC, CREDIT_NOTES_REQUESTED_TOPIC),
        consumed_topics=tuple(CONSUMER_HANDLERS),
        max_age=config.WORKER_METRICS_INTERVAL_SECONDS * 3,
    )
    logger.debug("queue_metrics_sampled", **result)
    return result
