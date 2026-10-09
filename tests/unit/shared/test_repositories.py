from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import AlreadyExistsError
from src.shared.infra.repositories import SqlAlchemyRepository


@dataclass
class FakeEntity(Entity):
    name: str = ""
    id: int | None = None


class NameTakenError(AlreadyExistsError):
    error_code = "NAME_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("name already taken")


class FakeRepo(SqlAlchemyRepository[FakeEntity]):
    __model__ = MagicMock
    __unique_errors__ = {"fakes_name_key": NameTakenError}


def _make_repo():
    session = MagicMock()
    mapper = MagicMock()
    mapper.to_dict.return_value = {"name": "test"}
    mapper.to_entity.return_value = FakeEntity(id=1, name="test")
    repo = FakeRepo(session, mapper)
    return repo, session, mapper


def test_save_always_flushes():
    repo, session, _ = _make_repo()
    repo._save()
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_create_flushes():
    repo, session, _ = _make_repo()
    entity = FakeEntity(name="test")
    repo.create(entity)
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_update_flushes():
    repo, session, _ = _make_repo()
    model = MagicMock()
    session.get.return_value = model
    entity = FakeEntity(id=1, name="updated")
    repo.update(entity)
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_delete_flushes():
    repo, session, _ = _make_repo()
    model = MagicMock()
    session.get.return_value = model
    repo.delete(1)
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def _violation(constraint: str) -> IntegrityError:
    orig = Exception("duplicate key value violates unique constraint")
    orig.diag = SimpleNamespace(constraint_name=constraint)  # ty: ignore[unresolved-attribute]
    return IntegrityError(statement="INSERT ...", params={}, orig=orig)


def test_known_unique_violation_becomes_its_domain_error():
    repo, session, _ = _make_repo()
    session.flush.side_effect = _violation("fakes_name_key")

    with pytest.raises(NameTakenError):
        repo.create(FakeEntity(name="test"))


def test_other_integrity_errors_propagate():
    repo, session, _ = _make_repo()
    session.flush.side_effect = _violation("some_other_key")

    with pytest.raises(IntegrityError):
        repo.create(FakeEntity(name="test"))


def test_first_for_update_locks_the_row():
    repo, session, _ = _make_repo()

    repo.first_for_update()

    session.query.return_value.filter.return_value.with_for_update.assert_called_once()
