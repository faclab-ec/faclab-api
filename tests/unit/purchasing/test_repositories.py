from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.purchasing.infra.mappers import PurchaseOrderMapper
from src.purchasing.infra.models import PurchaseOrderModel
from src.purchasing.infra.repositories import SqlAlchemyPurchaseOrderRepository
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.suppliers.infra.models import SupplierModel
from tests.sqlite import sqlite_session


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([SupplierModel, PurchaseOrderModel])
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


def test_last_sequence_only_counts_the_context_tenant(session):
    other = TenantContext(
        UUID("00000000-0000-4000-8000-0000000000b2"), TenantSource.TASK
    )
    with use_tenant(other):
        _add_orders(session, "PO-2026-0050")
    _add_orders(session, "PO-2026-0002")
    repo = SqlAlchemyPurchaseOrderRepository(session, PurchaseOrderMapper())

    assert repo.last_sequence_for_prefix("PO-2026-") == 2
    with use_tenant(other):
        assert repo.last_sequence_for_prefix("PO-2026-") == 50
