from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from wireup import injectable

from src.purchasing.app.repositories import (
    PurchaseOrderItemRepository,
    PurchaseOrderRepository,
)
from src.purchasing.domain.entities import PurchaseOrder
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode
from src.suppliers.app.repositories import SupplierRepository


def taxes_by_rate(
    breakdown: dict[TaxCode, tuple[Decimal, Decimal]],
) -> list[dict[str, Any]]:
    """El desglose por tarifa como lo muestran las respuestas: base imponible e
    IVA de cada código, a centavos, del de mayor tarifa al de menor (S5.7)"""
    return [
        {"tax_code": code, "rate": code.rate, "base": base, "tax": tax}
        for code, (base, tax) in sorted(
            breakdown.items(), key=lambda entry: (-entry[0].rate, entry[0].value)
        )
    ]


@dataclass
class GetAllPurchaseOrdersQuery(Query):
    status: str | None = None
    supplier_id: int | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllPurchaseOrdersQueryHandler(QueryHandler[GetAllPurchaseOrdersQuery, dict]):
    def __init__(
        self, repo: PurchaseOrderRepository, supplier_repo: SupplierRepository
    ):
        self.repo = repo
        self.supplier_repo = supplier_repo

    def _handle(self, query: GetAllPurchaseOrdersQuery) -> dict:
        filters = {}
        if query.status is not None:
            filters["status"] = query.status
        if query.supplier_id is not None:
            filters["supplier_id"] = query.supplier_id
        result = self.repo.paginate(limit=query.limit, offset=query.offset, **filters)

        supplier_names = {
            s.id: s.name
            for s in self.supplier_repo.get_by_ids(
                po["supplier_id"] for po in result["items"]
            )
        }
        for po in result["items"]:
            po["supplier_name"] = supplier_names.get(po["supplier_id"])
        return result


@dataclass
class GetPurchaseOrderByIdQuery(Query):
    id: int = 0


@injectable(lifetime="scoped")
class GetPurchaseOrderByIdQueryHandler(QueryHandler[GetPurchaseOrderByIdQuery, dict]):
    """La orden con su desglose de IVA por tarifa (S5.7)"""

    def __init__(
        self,
        repo: PurchaseOrderRepository,
        supplier_repo: SupplierRepository,
        item_repo: PurchaseOrderItemRepository,
    ):
        self.repo = repo
        self.supplier_repo = supplier_repo
        self.item_repo = item_repo

    def _handle(self, query: GetPurchaseOrderByIdQuery) -> dict:
        order = self.repo.get_by_id(query.id)
        if order is None:
            raise NotFoundError(f"Purchase order with id {query.id} not found")
        supplier = self.supplier_repo.get_by_id(order.supplier_id)
        items = self.item_repo.filter_by(purchase_order_id=order.require_id())
        return {
            **order.dict(),
            "supplier_name": supplier.name if supplier else None,
            "taxes": taxes_by_rate(PurchaseOrder.tax_breakdown(items)),
        }
