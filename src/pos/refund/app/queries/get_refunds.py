from dataclasses import dataclass

from wireup import injectable

from src.pos.refund.app.repositories import (
    RefundItemRepository,
    RefundPaymentRepository,
    RefundRepository,
)
from src.pos.refund.domain.specifications import RefundsByStatus, RefundsOfSale
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification, all_of


@dataclass
class GetRefundByIdQuery(Query):
    refund_id: int


@injectable(lifetime="scoped")
class GetRefundByIdQueryHandler(QueryHandler[GetRefundByIdQuery, dict]):
    def __init__(
        self,
        refund_repo: RefundRepository,
        refund_item_repo: RefundItemRepository,
        refund_payment_repo: RefundPaymentRepository,
    ):
        self.refund_repo = refund_repo
        self.refund_item_repo = refund_item_repo
        self.refund_payment_repo = refund_payment_repo

    def _handle(self, query: GetRefundByIdQuery) -> dict:
        refund = self.refund_repo.get_by_id(query.refund_id)
        if not refund:
            raise NotFoundError(f"Refund with id {query.refund_id} not found")

        items = self.refund_item_repo.filter_by(refund_id=query.refund_id)
        payments = self.refund_payment_repo.filter_by(refund_id=query.refund_id)

        result = refund.dict()
        result["items"] = [{**item.dict(), "subtotal": item.subtotal} for item in items]
        result["payments"] = [p.dict() for p in payments]
        return result


@dataclass
class GetRefundsQuery(Query):
    sale_id: int | None = None
    status: str | None = None
    limit: int | None = 100
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetRefundsQueryHandler(QueryHandler[GetRefundsQuery, dict]):
    def __init__(self, refund_repo: RefundRepository):
        self.refund_repo = refund_repo

    def _handle(self, query: GetRefundsQuery) -> dict:
        specs: list[Specification] = []
        if query.sale_id is not None:
            specs.append(RefundsOfSale(query.sale_id))
        if query.status is not None:
            specs.append(RefundsByStatus(query.status))
        # Newest first: this is the refund history
        return self.refund_repo.paginate_by_spec(
            all_of(specs),
            limit=query.limit,
            offset=query.offset,
            order_by="id",
            desc_order=True,
        )
