"""The worker marks EXPIRED the open quotes past their validity, of every
tenant (S5.4)"""

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.quotes.domain.entities import QuoteStatus
from src.quotes.infra.expiration import expire_quotes
from src.quotes.infra.models import QuoteModel
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session
from tests.unit.quotes.fakes import TODAY

OTHER_TENANT = UUID("00000000-0000-0000-0000-0000000000b2")
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([QuoteModel])
    db.add(TenantModel(id=OTHER_TENANT, ruc="1790000000001", legal_name="Otra"))
    db.commit()
    yield db
    db.close()


def _add(session: Session, number: str, status: QuoteStatus, valid_until) -> None:
    session.add(
        QuoteModel(
            branch_id=1,
            number=number,
            status=status.value,
            issue_date=min(valid_until, TODAY),
            valid_until=valid_until,
        )
    )
    session.flush()


def test_the_open_quotes_past_their_date_expire_in_every_tenant(session):
    _add(session, "COT-001-000001", QuoteStatus.DRAFT, YESTERDAY)
    _add(session, "COT-001-000002", QuoteStatus.SENT, YESTERDAY)
    _add(session, "COT-001-000003", QuoteStatus.ACCEPTED, TODAY)
    _add(session, "COT-001-000004", QuoteStatus.CONVERTED, YESTERDAY)
    with use_tenant(TenantContext(OTHER_TENANT, TenantSource.TASK)):
        _add(session, "COT-001-000001", QuoteStatus.ACCEPTED, YESTERDAY)
    session.commit()

    expired = expire_quotes(sessionmaker(bind=session.get_bind()), TODAY)

    assert expired == 3
    session.expire_all()
    rows = session.execute(
        select(QuoteModel.number, QuoteModel.status).where(
            QuoteModel.tenant_id != OTHER_TENANT
        )
    ).all()
    statuses = dict(rows)
    assert statuses == {
        "COT-001-000001": "EXPIRED",
        "COT-001-000002": "EXPIRED",
        # Its last day is today: still in force
        "COT-001-000003": "ACCEPTED",
        "COT-001-000004": "CONVERTED",
    }
    # A second pass finds nothing
    assert expire_quotes(sessionmaker(bind=session.get_bind()), TODAY) == 0
