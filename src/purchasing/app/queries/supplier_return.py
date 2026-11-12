"""Devoluciones a proveedor (S5.7). La lista es un read model: consulta los
modelos con el filtro de la empresa (`tenant_criteria`) en cada tabla que lee."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.app.product_names import with_product_names
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.purchasing.app.commands.supplier_return import (
    describe_return,
    describe_return_item,
)
from src.purchasing.app.queries.purchase_order import taxes_by_rate
from src.purchasing.app.repositories import (
    PurchaseOrderRepository,
    SupplierReturnItemRepository,
    SupplierReturnRepository,
)
from src.purchasing.domain.entities import SupplierReturn
from src.purchasing.infra.models import PurchaseOrderModel, SupplierReturnModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.infra.tenant import tenant_criteria
from src.suppliers.app.repositories import SupplierRepository
from src.suppliers.infra.models import SupplierModel


@dataclass
class GetSupplierReturnsQuery(Query):
    supplier_id: int | None = None
    purchase_order_id: int | None = None
    status: str | None = None
    limit: int | None = 50
    offset: int | None = 0


@injectable(lifetime="scoped")
class GetSupplierReturnsQueryHandler(QueryHandler[GetSupplierReturnsQuery, dict]):
    """Las devoluciones, la más reciente primero, con su proveedor y su orden"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetSupplierReturnsQuery) -> dict:
        rows = (
            self.session.query(
                SupplierReturnModel, SupplierModel.name, PurchaseOrderModel.order_number
            )
            .join(SupplierModel, SupplierModel.id == SupplierReturnModel.supplier_id)
            .join(
                PurchaseOrderModel,
                PurchaseOrderModel.id == SupplierReturnModel.purchase_order_id,
            )
            .filter(
                *tenant_criteria(SupplierReturnModel, SupplierModel, PurchaseOrderModel)
            )
        )
        if query.supplier_id is not None:
            rows = rows.filter(SupplierReturnModel.supplier_id == query.supplier_id)
        if query.purchase_order_id is not None:
            rows = rows.filter(
                SupplierReturnModel.purchase_order_id == query.purchase_order_id
            )
        if query.status is not None:
            rows = rows.filter(SupplierReturnModel.status == query.status)
        total = rows.with_entities(func.count(SupplierReturnModel.id)).scalar()
        page = (
            rows.order_by(SupplierReturnModel.id.desc())
            .limit(query.limit)
            .offset(query.offset)
            .all()
        )
        return {
            "items": [
                {
                    **_row(model),
                    "supplier_name": supplier_name,
                    "order_number": order_number,
                }
                for model, supplier_name, order_number in page
            ],
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
        }


def _row(model: SupplierReturnModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "number": model.number,
        "supplier_id": model.supplier_id,
        "purchase_order_id": model.purchase_order_id,
        "status": model.status,
        "notes": model.notes,
        "supplier_credit_note_number": model.supplier_credit_note_number,
        "subtotal": model.subtotal,
        "tax": model.tax,
        "total": model.total,
        "credited_amount": model.credited_amount,
        "refund_due": model.total - model.credited_amount,
        "confirmed_at": model.confirmed_at,
        "confirmed_by": model.confirmed_by,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


@dataclass
class GetSupplierReturnByIdQuery(Query):
    id: int = 0


@injectable(lifetime="scoped")
class GetSupplierReturnByIdQueryHandler(QueryHandler[GetSupplierReturnByIdQuery, dict]):
    """La devolución con su proveedor, su orden y su IVA por tarifa"""

    def __init__(
        self,
        repo: SupplierReturnRepository,
        item_repo: SupplierReturnItemRepository,
        po_repo: PurchaseOrderRepository,
        supplier_repo: SupplierRepository,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.po_repo = po_repo
        self.supplier_repo = supplier_repo

    def _handle(self, query: GetSupplierReturnByIdQuery) -> dict:
        supplier_return = self.repo.get_by_id(query.id)
        if supplier_return is None:
            raise NotFoundError(f"Supplier return with id {query.id} not found")
        supplier = self.supplier_repo.get_by_id(supplier_return.supplier_id)
        order = self.po_repo.get_by_id(supplier_return.purchase_order_id)
        items = self.item_repo.filter_by(
            supplier_return_id=supplier_return.require_id()
        )
        return {
            **describe_return(supplier_return),
            "supplier_name": supplier.name if supplier else None,
            "order_number": order.order_number if order else None,
            "taxes": taxes_by_rate(SupplierReturn.tax_breakdown(items)),
        }


@dataclass
class GetSupplierReturnItemsQuery(Query):
    supplier_return_id: int = 0


@injectable(lifetime="scoped")
class GetSupplierReturnItemsQueryHandler(
    QueryHandler[GetSupplierReturnItemsQuery, list[dict]]
):
    def __init__(
        self,
        repo: SupplierReturnRepository,
        item_repo: SupplierReturnItemRepository,
        product_repo: ProductRepository,
        presentations: ProductPresentationRepository,
    ):
        self.repo = repo
        self.item_repo = item_repo
        self.product_repo = product_repo
        self.presentations = presentations

    def _handle(self, query: GetSupplierReturnItemsQuery) -> list[dict]:
        if self.repo.get_by_id(query.supplier_return_id) is None:
            raise NotFoundError(
                f"Supplier return with id {query.supplier_return_id} not found"
            )
        items = sorted(
            self.item_repo.filter_by(supplier_return_id=query.supplier_return_id),
            key=lambda item: item.require_id(),
        )
        return with_product_names(
            [describe_return_item(item) for item in items],
            self.product_repo,
            self.presentations,
        )
