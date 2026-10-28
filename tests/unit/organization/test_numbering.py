from collections.abc import Iterator
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.organization.app.numbering import DocumentNumbering
from src.organization.domain.entities import Branch
from src.organization.domain.numbering import (
    DocumentType,
    document_number,
    tenant_document_number,
)
from src.organization.infra.models import DocumentSequenceModel
from src.organization.infra.repositories import SqlAlchemyDocumentSequenceRepository
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([DocumentSequenceModel])
    yield db
    db.close()


def test_a_document_number_has_prefix_establishment_and_six_digits():
    assert document_number(DocumentType.SALE, "001", 123) == "V-001-000123"
    assert document_number(DocumentType.REFUND, "002", 45) == "D-002-000045"
    # It keeps growing past six digits
    assert document_number(DocumentType.SALE, "001", 1_000_000) == "V-001-1000000"


def test_numbers_are_consecutive_per_branch_and_type(session):
    repo = SqlAlchemyDocumentSequenceRepository(session)

    sales_1 = [repo.next_value(1, DocumentType.SALE) for _ in range(3)]
    refunds_1 = [repo.next_value(1, DocumentType.REFUND) for _ in range(2)]
    sales_2 = [repo.next_value(2, DocumentType.SALE) for _ in range(2)]

    assert sales_1 == [1, 2, 3]
    assert refunds_1 == [1, 2]
    assert sales_2 == [1, 2]
    counters = session.scalars(select(DocumentSequenceModel)).all()
    assert len(counters) == 3


def test_each_tenant_has_its_own_counters(session):
    other = UUID("00000000-0000-4000-8000-00000000000b")
    session.add(TenantModel(id=other, ruc="1799999991001", legal_name="Otra"))
    session.commit()
    repo = SqlAlchemyDocumentSequenceRepository(session)
    repo.next_value(1, DocumentType.SALE)

    with use_tenant(TenantContext(other, TenantSource.TASK)):
        assert repo.next_value(1, DocumentType.SALE) == 1
    assert repo.next_value(1, DocumentType.SALE) == 2


def test_a_tenant_document_number_has_prefix_year_and_four_digits():
    assert (
        tenant_document_number(DocumentType.PURCHASE_ORDER, 2026, 7) == "PO-2026-0007"
    )
    assert (
        tenant_document_number(DocumentType.PURCHASE_ORDER, 2027, 10_000)
        == "PO-2027-10000"
    )


def test_a_tenant_counter_has_no_branch_and_is_apart_from_the_branches(session):
    repo = SqlAlchemyDocumentSequenceRepository(session)

    orders = [repo.next_value(None, DocumentType.PURCHASE_ORDER) for _ in range(3)]
    repo.next_value(1, DocumentType.PURCHASE_ORDER)

    assert orders == [1, 2, 3]
    assert repo.next_value(None, DocumentType.PURCHASE_ORDER) == 4
    counters = session.scalars(
        select(DocumentSequenceModel).order_by(DocumentSequenceModel.id)
    ).all()
    assert [(c.branch_id, c.last_value) for c in counters] == [(None, 4), (1, 1)]


def test_each_tenant_has_its_own_tenant_counter(session):
    other = UUID("00000000-0000-4000-8000-00000000000b")
    session.add(TenantModel(id=other, ruc="1799999991001", legal_name="Otra"))
    session.commit()
    repo = SqlAlchemyDocumentSequenceRepository(session)
    repo.next_value(None, DocumentType.PURCHASE_ORDER)

    with use_tenant(TenantContext(other, TenantSource.TASK)):
        assert repo.next_value(None, DocumentType.PURCHASE_ORDER) == 1
    assert repo.next_value(None, DocumentType.PURCHASE_ORDER) == 2


def test_numbering_in_the_tenant_needs_no_branch():
    sequences = MagicMock()
    sequences.next_value.return_value = 12
    branches = MagicMock()

    number = DocumentNumbering(sequences, branches).next_in_tenant(
        DocumentType.PURCHASE_ORDER, 2026
    )

    sequences.next_value.assert_called_once_with(None, DocumentType.PURCHASE_ORDER)
    branches.get_by_id.assert_not_called()
    assert number == "PO-2026-0012"


def test_numbering_formats_with_the_branch_code():
    sequences = MagicMock()
    sequences.next_value.return_value = 15
    branches = MagicMock()
    branches.get_by_id.return_value = Branch(
        id=2, establishment_code="002", name="Norte"
    )

    number = DocumentNumbering(sequences, branches).next(2, DocumentType.SALE)

    sequences.next_value.assert_called_once_with(2, DocumentType.SALE)
    assert number == "V-002-000015"


def test_numbering_needs_the_branch():
    branches = MagicMock()
    branches.get_by_id.return_value = None
    sequences = MagicMock()

    with pytest.raises(NotFoundError):
        DocumentNumbering(sequences, branches).next(9, DocumentType.SALE)
    sequences.next_value.assert_not_called()
