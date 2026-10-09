from unittest.mock import ANY, MagicMock

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

    GetRefundsQueryHandler(repo).handle(GetRefundsQuery(limit=10, offset=0))

    repo.paginate_by_spec.assert_called_once_with(
        ANY, limit=10, offset=0, order_by="id", desc_order=True
    )


def test_refunds_filter_by_sale_and_status():
    repo = MagicMock()
    repo.paginate_by_spec.return_value = {"total": 0, "items": []}

    GetRefundsQueryHandler(repo).handle(
        GetRefundsQuery(sale_id=7, status=RefundStatus.PENDING)
    )

    spec = repo.paginate_by_spec.call_args.args[0]
    assert spec.is_satisfied_by(_refund(status=RefundStatus.PENDING))
    assert not spec.is_satisfied_by(_refund(status=RefundStatus.COMPLETED))
    assert not spec.is_satisfied_by(
        _refund(original_sale_id=8, status=RefundStatus.PENDING)
    )
