from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import event

from src.shared.domain.exceptions import ApplicationError
from src.shared.domain.tenant import (
    TenantContext,
    TenantContextRequiredError,
    TenantMismatchError,
    TenantSource,
    use_tenant,
)
from src.shared.infra.database import (
    assign_tenant,
    create_session_factory,
    create_session_maker,
    set_tenant_setting,
)
from tests.tenant_notes import GlobalNoteModel, NoteModel, ScratchBase


class KeepsChangesError(ApplicationError):
    commit_transaction = True


def _run(error: Exception):
    session = MagicMock()
    with patch(
        "src.shared.infra.database.create_session_maker", return_value=lambda: session
    ):
        get_db_session = create_session_factory("sqlite://")
    scope = get_db_session()
    next(scope)
    with pytest.raises(type(error)):
        scope.throw(error)
    return session


def test_an_error_rolls_the_request_back():
    session = _run(ApplicationError("boom"))

    session.rollback.assert_called_once()
    session.commit.assert_not_called()


def test_an_error_that_keeps_its_changes_commits_them():
    session = _run(KeepsChangesError("locked"))

    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()


TENANT = TenantContext(UUID("00000000-0000-4000-8000-0000000000a1"), TenantSource.TASK)


def _connection(dialect: str) -> MagicMock:
    connection = MagicMock()
    connection.dialect.name = dialect
    return connection


def test_a_transaction_in_a_tenant_sets_it_locally_on_postgres():
    connection = _connection("postgresql")

    with use_tenant(TENANT):
        set_tenant_setting(MagicMock(), MagicMock(), connection)

    statement, params = connection.execute.call_args.args
    assert str(statement) == "SELECT set_config('app.tenant_id', :tenant_id, true)"
    assert params == {"tenant_id": str(TENANT.tenant_id)}


def test_a_transaction_without_a_tenant_sets_nothing():
    connection = _connection("postgresql")

    set_tenant_setting(MagicMock(), MagicMock(), connection)

    connection.execute.assert_not_called()


def test_other_databases_are_left_alone():
    connection = _connection("sqlite")

    with use_tenant(TENANT):
        set_tenant_setting(MagicMock(), MagicMock(), connection)

    connection.execute.assert_not_called()


def test_every_session_maker_sets_the_tenant_when_a_transaction_begins():
    factory = create_session_maker("sqlite://")

    assert event.contains(factory, "after_begin", set_tenant_setting)


def test_every_session_maker_assigns_the_tenant_before_a_flush():
    factory = create_session_maker("sqlite://")

    assert event.contains(factory, "before_flush", assign_tenant)


OTHER = UUID("00000000-0000-4000-8000-0000000000b2")


@pytest.fixture
def notes_session():
    factory = create_session_maker("sqlite://")
    ScratchBase.metadata.create_all(factory.kw["bind"])
    session = factory()
    yield session
    session.close()


def test_a_new_row_gets_the_context_tenant(notes_session):
    note = NoteModel(title="direct")
    notes_session.add(note)

    with use_tenant(TENANT):
        notes_session.flush()

    assert note.tenant_id == TENANT.tenant_id


def test_a_new_row_of_another_tenant_is_rejected(notes_session):
    notes_session.add(NoteModel(title="foreign", tenant_id=OTHER))

    with use_tenant(TENANT), pytest.raises(TenantMismatchError):
        notes_session.flush()


def test_without_a_context_no_tenant_row_is_written(notes_session):
    notes_session.add(NoteModel(title="orphan"))

    with pytest.raises(TenantContextRequiredError, match="writing NoteModel"):
        notes_session.flush()


def test_a_model_without_the_mark_is_left_alone(notes_session):
    note = GlobalNoteModel(title="global")
    notes_session.add(note)
    notes_session.flush()

    assert note.tenant_id is None
