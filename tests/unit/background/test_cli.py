from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.background import cli, messaging
from src.shared.infra.database import Base
from src.shared.infra.kafka.dead_letters import DeadLetter, DeadLetterStore
from src.shared.infra.kafka.models import DeadLetterModel
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000a1")


@pytest.fixture
def session_factory(monkeypatch):
    """The CLI's faclab_worker sessions, on SQLite"""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables[model.__tablename__]
            for model in (OutboxMessageModel, DeadLetterModel)
        ],
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(cli, "worker_session_maker", lambda: factory)
    return factory


def _outbox(session_factory, event_id: str, status: OutboxStatus) -> int:
    with session_factory() as session:
        message = OutboxMessageModel(
            event_id=event_id,
            event_type="SaleConfirmed",
            topic="sales.confirmed",
            payload={"id": event_id},
            tenant_id=TENANT_ID,
            headers={},
            status=status.value,
            attempts=10 if status == OutboxStatus.FAILED else 0,
            last_error="message too large" if status == OutboxStatus.FAILED else None,
        )
        session.add(message)
        session.commit()
        return message.id


def _dead_letter(session_factory) -> int:
    DeadLetterStore(session_factory).record(
        DeadLetter(
            consumer_group="faclab-core",
            topic="invoices",
            partition=0,
            offset=3,
            key=None,
            tenant_id=TENANT_ID,
            headers={},
            value='{"saleId": "1"}',
            error="database is down",
            attempts=5,
        )
    )
    with session_factory() as session:
        return session.query(DeadLetterModel).one().id


@pytest.fixture
def dispatch(monkeypatch) -> MagicMock:
    """The consumer's dispatch; the container isn't needed"""
    consumer = MagicMock()
    monkeypatch.setattr(messaging, "create_consumer", lambda: consumer)
    monkeypatch.setattr("src.container.create_wireup_container", lambda: None)
    return consumer.dispatch


def test_it_lists_the_failed_messages(session_factory, capsys):
    failed = _outbox(session_factory, "a", OutboxStatus.FAILED)
    _outbox(session_factory, "b", OutboxStatus.PUBLISHED)

    assert cli.main(["outbox-failed"]) == 0

    out = capsys.readouterr().out
    assert out.startswith(f"{failed}\t{TENANT_ID}\tsales.confirmed\tSaleConfirmed\t")
    assert "message too large" in out
    assert "1 failed message(s)" in out


def test_a_retry_records_who_did_it(session_factory):
    failed = _outbox(session_factory, "a", OutboxStatus.FAILED)

    assert cli.main(["outbox-retry", str(failed), "--by", "dbs"]) == 0

    with session_factory() as session:
        message = session.get(OutboxMessageModel, failed)
        assert message is not None
        assert (message.status, message.attempts, message.retried_by) == (
            "pending",
            0,
            "dbs",
        )
        assert message.retried_at is not None


def test_a_retry_needs_ids_or_all_and_an_author(session_factory):
    assert cli.main(["outbox-retry", "--by", "dbs"]) == 2
    assert cli.main(["outbox-retry", "1", "--all", "--by", "dbs"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["outbox-retry", "--all"])


def test_retrying_all_puts_every_failed_message_back(session_factory):
    _outbox(session_factory, "a", OutboxStatus.FAILED)
    _outbox(session_factory, "b", OutboxStatus.FAILED)

    assert cli.main(["outbox-retry", "--all", "--by", "dbs"]) == 0

    with session_factory() as session:
        statuses = {m.status for m in session.query(OutboxMessageModel)}
    assert statuses == {"pending"}


def test_a_dead_letter_is_reprocessed_through_its_handler(session_factory, dispatch):
    letter_id = _dead_letter(session_factory)

    assert cli.main(["dead-letter-reprocess", str(letter_id), "--by", "dbs"]) == 0

    dispatch.assert_called_once_with("invoices", b'{"saleId": "1"}', [])
    with session_factory() as session:
        letter = session.get(DeadLetterModel, letter_id)
        assert letter is not None
        assert (letter.status, letter.reprocessed_by) == ("reprocessed", "dbs")


def test_a_dead_letter_that_fails_again_exits_with_an_error(
    session_factory, dispatch, capsys
):
    letter_id = _dead_letter(session_factory)
    dispatch.side_effect = ConnectionError("still down")

    assert cli.main(["dead-letter-reprocess", str(letter_id), "--by", "dbs"]) == 1

    assert "failed again: still down" in capsys.readouterr().err
    assert cli.main(["dead-letters"]) == 0


def test_an_unknown_dead_letter_exits_with_an_error(session_factory, dispatch):
    assert cli.main(["dead-letter-reprocess", "99", "--by", "dbs"]) == 1
    dispatch.assert_not_called()
