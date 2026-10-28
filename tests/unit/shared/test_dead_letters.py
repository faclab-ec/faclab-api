from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.shared.infra.database import Base
from src.shared.infra.kafka.dead_letters import (
    DeadLetter,
    DeadLetterStore,
    list_pending,
    reprocess,
)
from src.shared.infra.kafka.models import DeadLetterModel

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000a1")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[DeadLetterModel.__tablename__]]
    )
    return sessionmaker(bind=engine)


def _letter(offset: int = 7) -> DeadLetter:
    return DeadLetter(
        consumer_group="faclab-core",
        topic="invoices",
        partition=0,
        offset=offset,
        key=str(TENANT_ID),
        tenant_id=TENANT_ID,
        headers={"faclab-tenant-id": str(TENANT_ID)},
        value='{"saleId": "1"}',
        error="database is down",
        attempts=5,
    )


def test_a_message_is_kept_once_even_if_it_comes_again(session_factory):
    store = DeadLetterStore(session_factory)

    store.record(_letter())
    store.record(_letter())
    store.record(_letter(offset=8))

    letters = list_pending(session_factory)
    assert [letter.kafka_offset for letter in letters] == [7, 8]
    assert letters[0].headers == {"faclab-tenant-id": str(TENANT_ID)}
    assert (letters[0].status, letters[0].error) == ("pending", "database is down")


def test_reprocessing_delivers_the_message_and_records_who_did_it(session_factory):
    DeadLetterStore(session_factory).record(_letter())
    [letter] = list_pending(session_factory)
    delivered = []
    at = datetime(2026, 10, 28, 12, 0)

    result = reprocess(
        session_factory,
        letter.id,
        "ops",
        lambda topic, value, headers: delivered.append((topic, value, list(headers))),
        now=at,
    )

    assert result is not None
    assert (result.status, result.reprocessed_by, result.reprocessed_at) == (
        "reprocessed",
        "ops",
        at,
    )
    assert delivered == [
        (
            "invoices",
            b'{"saleId": "1"}',
            [("faclab-tenant-id", str(TENANT_ID).encode())],
        )
    ]
    assert list_pending(session_factory) == []
    # Done once: a second run finds nothing to do
    again = reprocess(
        session_factory,
        letter.id,
        "ops",
        lambda topic, value, headers: delivered.append((topic, value, headers)),
    )
    assert again is None
    assert len(delivered) == 1


def test_a_failed_reprocess_keeps_the_letter_pending(session_factory):
    DeadLetterStore(session_factory).record(_letter())
    [letter] = list_pending(session_factory)

    def failing(_topic, _value, _headers):
        raise ValueError("sale is locked")

    result = reprocess(session_factory, letter.id, "ops", failing)

    assert result is not None
    assert (result.status, result.attempts, result.error) == (
        "pending",
        6,
        "sale is locked",
    )
    assert result.reprocessed_by is None
