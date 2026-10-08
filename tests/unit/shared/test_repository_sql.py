from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.shared.infra.database import Base
from src.suppliers.infra.mappers import SupplierMapper
from src.suppliers.infra.models import SupplierModel
from src.suppliers.infra.repositories import SqlAlchemySupplierRepository


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[SupplierModel.__tablename__]]
    )
    db = sessionmaker(bind=engine)()
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
