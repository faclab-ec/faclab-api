from unittest.mock import ANY, MagicMock

from src.invoicing.domain.entities import CreditNote
from src.pos.refund.app.queries.get_refunds import (
    GetRefundsQuery,
    GetRefundsQueryHandler,
)
from src.pos.refund.domain.entities import Refund, RefundStatus


def _refund(
    original_sale_id: int = 7, status: RefundStatus = RefundStatus.PENDING
) -> Refund:
    return Refund(id=1, original_sale_id=original_sale_id, status=status)


def test_refunds_are_listed_newest_first():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {"total": 0, "items": []}

    GetRefundsQueryHandler(repo, MagicMock()).handle(
        GetRefundsQuery(limit=10, offset=0)
    )

    repo.paginate_by_spec.assert_called_once_with(
        ANY, limit=10, offset=0, order_by="id", desc_order=True
    )


def test_refunds_filter_by_sale_and_status():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {"total": 0, "items": []}

    GetRefundsQueryHandler(repo, MagicMock()).handle(
        GetRefundsQuery(sale_id=7, status=RefundStatus.PENDING)
    )

    spec = repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(_refund(status=RefundStatus.PENDING))
    assert not spec.is_satisfied_by(_refund(status=RefundStatus.COMPLETED))
    assert not spec.is_satisfied_by(
        _refund(original_sale_id=8, status=RefundStatus.PENDING)
    )


def test_each_refund_of_the_page_shows_its_credit_note():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {
        "total": 2,
        "items": [{"id": 1, "total": 10}, {"id": 2, "total": 20}],
    }
    credit_notes = MagicMock()
    credit_notes.of_refunds.return_value = [
        CreditNote(id=7, sale_id=1, refund_id=2, invoice_id="inv", reason="x")
    ]

    page = GetRefundsQueryHandler(repo, credit_notes).handle(GetRefundsQuery())

    assert list(credit_notes.of_refunds.call_args.args[0]) == [1, 2]
    assert page["items"][0]["credit_note"] is None
    assert page["items"][1]["credit_note"]["id"] == 7
    assert page["items"][1]["total"] == 20
