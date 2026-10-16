from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from src.suppliers.infra.mappers import SupplierMapper
from src.suppliers.infra.models import SupplierModel
from src.suppliers.infra.repositories import SqlAlchemySupplierRepository
from tests.sqlite import sqlite_session


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([SupplierModel])
    for n in (1, 2, 3):
        db.add(SupplierModel(id=n, name=f"Supplier {n}", tax_id=f"099000000{n}001"))
    db.commit()
    yield db
    db.close()


def test_get_by_ids_returns_only_requested_entities(session):
    repo = SqlAlchemySupplierRepository(session, SupplierMapper())

    suppliers = repo.get_by_ids([1, 3, 3, 99])

    assert sorted((s.id, s.name) for s in suppliers) == [
        (1, "Supplier 1"),
        (3, "Supplier 3"),
    ]


def test_get_by_ids_with_no_ids_skips_the_query(session):
    repo = SqlAlchemySupplierRepository(session, SupplierMapper())

    assert repo.get_by_ids([]) == []
