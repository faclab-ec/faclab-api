from dataclasses import dataclass
from typing import Any

from wireup import injectable

from src.catalog.product.app.product_names import with_product_names
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.purchasing.app.repositories import PurchaseOrderItemRepository
from src.purchasing.domain.entities import PurchaseOrderItem
from src.shared.app.queries import Query, QueryHandler


def describe_order_item(item: PurchaseOrderItem) -> dict[str, Any]:
    """La línea con su subtotal sin IVA, a precisión completa (S5.7)"""
    return {**item.dict(), "subtotal": item.subtotal}


@dataclass
class GetPurchaseOrderItemsByPOQuery(Query):
    purchase_order_id: int = 0


@injectable(lifetime="scoped")
class GetPurchaseOrderItemsByPOQueryHandler(
    QueryHandler[GetPurchaseOrderItemsByPOQuery, list[dict]]
):
    def __init__(
        self,
        repo: PurchaseOrderItemRepository,
        product_repo: ProductRepository,
        presentations: ProductPresentationRepository,
    ):
        self.repo = repo
        self.product_repo = product_repo
        self.presentations = presentations

    def _handle(self, query: GetPurchaseOrderItemsByPOQuery) -> list[dict]:
        items = self.repo.filter_by(purchase_order_id=query.purchase_order_id)
        return with_product_names(
            [describe_order_item(item) for item in items],
            self.product_repo,
            self.presentations,
        )
