from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.purchasing.infra.mappers import PurchaseOrderMapper
from src.purchasing.infra.models import PurchaseOrderModel
from src.purchasing.infra.repositories import SqlAlchemyPurchaseOrderRepository
from src.shared.infra.database import Base
from src.suppliers.infra.models import SupplierModel


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Base.metadata.tables[model.__tablename__]
        for model in (SupplierModel, PurchaseOrderModel)
    ]
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


def _add_orders(session: Session, *numbers: str) -> None:
    for number in numbers:
        session.add(PurchaseOrderModel(supplier_id=1, order_number=number))
    session.commit()


def test_last_sequence_ignores_gaps_left_by_deleted_orders(session):
    # PO-2026-0002 was a deleted draft: count+1 would produce 0003 again
    _add_orders(session, "PO-2026-0001", "PO-2026-0003")
    repo = SqlAlchemyPurchaseOrderRepository(session, PurchaseOrderMapper())

    assert repo.last_sequence_for_prefix("PO-2026-") == 3


def test_last_sequence_only_counts_matching_prefix(session):
    _add_orders(session, "PO-2025-0042", "PO-2026-0007")
    repo = SqlAlchemyPurchaseOrderRepository(session, PurchaseOrderMapper())

    assert repo.last_sequence_for_prefix("PO-2026-") == 7
    assert repo.last_sequence_for_prefix("PO-2027-") == 0


def test_last_sequence_compares_numerically(session):
    _add_orders(session, "PO-2026-9999", "PO-2026-10000")
    repo = SqlAlchemyPurchaseOrderRepository(session, PurchaseOrderMapper())

    assert repo.last_sequence_for_prefix("PO-2026-") == 10000
