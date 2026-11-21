from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.background import queue_metrics
from src.shared.infra.database import Base
from src.shared.infra.kafka.models import DeadLetterModel, DeadLetterStatus
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus

TENANT_A = UUID("00000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("00000000-0000-4000-8000-0000000000b2")
NOW = datetime(2026, 11, 21, 12, 0)

OUTBOX_TOPICS = ("sales.confirmed", "credit_notes.requested")
CONSUMED_TOPICS = ("invoices", "credit_notes.results")


@pytest.fixture
def session_factory():
    """faclab_worker's sessions, on SQLite: every tenant's rows"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables[model.__tablename__]
            for model in (OutboxMessageModel, DeadLetterModel)
        ],
    )
    return sessionmaker(bind=engine)


def _outbox(session_factory, topic, status, age_seconds, tenant=TENANT_A):
    with session_factory() as session:
        count = session.query(OutboxMessageModel).count()
        session.add(
            OutboxMessageModel(
                event_id=f"e-{count}",
                event_type="Test",
                topic=topic,
                payload={},
                tenant_id=tenant,
                headers={},
                status=status.value,
                created_at=NOW - timedelta(seconds=age_seconds),
            )
        )
        session.commit()


def _dead_letter(session_factory, topic, status=DeadLetterStatus.PENDING):
    with session_factory() as session:
        count = session.query(DeadLetterModel).count()
        session.add(
            DeadLetterModel(
                consumer_group="faclab-core",
                topic=topic,
                kafka_partition=0,
                kafka_offset=count,
                headers={},
                error="boom",
                attempts=5,
                status=status.value,
            )
        )
        session.commit()


def _sample(session_factory):
    return queue_metrics.sample_queues(
        session_factory, OUTBOX_TOPICS, CONSUMED_TOPICS, max_age=180, now=NOW
    )


def test_counts_the_queues_of_every_tenant_by_topic(session_factory):
    _outbox(session_factory, "sales.confirmed", OutboxStatus.PENDING, 30)
    _outbox(session_factory, "sales.confirmed", OutboxStatus.PENDING, 400, TENANT_B)
    _outbox(session_factory, "sales.confirmed", OutboxStatus.PUBLISHED, 900)
    _outbox(session_factory, "credit_notes.requested", OutboxStatus.FAILED, 9000)
    _dead_letter(session_factory, "invoices")
    _dead_letter(session_factory, "invoices", DeadLetterStatus.REPROCESSED)

    sample = _sample(session_factory)

    assert sample["outbox_pending"] == {
        "credit_notes.requested": 0,
        "sales.confirmed": 2,
    }
    assert sample["outbox_failed"] == {
        "credit_notes.requested": 1,
        "sales.confirmed": 0,
    }
    # The oldest one still waiting; a failed message no longer waits
    assert sample["outbox_oldest_age"] == {
        "credit_notes.requested": 0,
        "sales.confirmed": 400,
    }
    assert sample["dead_letters_pending"] == {
        "credit_notes.results": 0,
        "invoices": 1,
    }


def test_empty_queues_read_zero_on_every_known_topic(session_factory):
    sample = _sample(session_factory)

    assert all(value == 0 for values in sample.values() for value in values.values())
    assert set(sample["outbox_pending"]) == set(OUTBOX_TOPICS)
    assert set(sample["dead_letters_pending"]) == set(CONSUMED_TOPICS)


def test_an_unknown_topic_still_shows(session_factory):
    _outbox(session_factory, "legacy.topic", OutboxStatus.PENDING, 5)

    assert _sample(session_factory)["outbox_pending"]["legacy.topic"] == 1


def test_the_gauges_export_the_sample(session_factory, recorded_metrics):
    _outbox(session_factory, "sales.confirmed", OutboxStatus.PENDING, 120)
    _dead_letter(session_factory, "credit_notes.results")

    _sample(session_factory)
    collected = recorded_metrics.collect()

    topic = "messaging.destination.name"
    assert (1, {topic: "sales.confirmed"}) in collected.points("faclab.outbox.pending")
    assert (120, {topic: "sales.confirmed"}) in collected.points(
        "faclab.outbox.oldest_age"
    )
    assert (0, {topic: "sales.confirmed"}) in collected.points("faclab.outbox.failed")
    assert (1, {topic: "credit_notes.results"}) in collected.points(
        "faclab.dead_letters.pending"
    )
    assert collected.units["faclab.outbox.oldest_age"] == "s"
    assert collected.units["faclab.outbox.pending"] == "{message}"


def test_the_worker_task_samples_every_topic_core_uses(session_factory, monkeypatch):
    from src.background.tasks import periodic_tasks
    from src.shared.infra import database

    monkeypatch.setattr(database, "worker_session_maker", lambda: session_factory)

    sample = queue_metrics.sample()

    assert set(sample["outbox_pending"]) == {
        "sales.confirmed",
        "credit_notes.requested",
    }
    assert set(sample["dead_letters_pending"]) == {"invoices", "credit_notes.results"}
    assert "queue_metrics" in {task.name for task in periodic_tasks()}
