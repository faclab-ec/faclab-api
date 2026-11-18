from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.public_api.app.listing import Page, PageRequest, ordering, paginate
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria

SORT_FIELDS = {
    "id": StockModel.id,
    "productId": StockModel.product_id,
    "updatedAt": StockModel.updated_at,
}


@dataclass
class ListApiStockQuery(Query):
    branch_id: int
    page: PageRequest = field(default_factory=PageRequest)
    product_id: int | None = None


@injectable(lifetime="scoped")
class ListApiStockQueryHandler(QueryHandler[ListApiStockQuery, Page]):
    """The stock rows of a branch: one per product and location of its
    warehouses, in base units. `available` is what a sale can take: the
    quantity minus what confirmed transfers reserve."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiStockQuery) -> Page:
        statement = (
            select(StockModel, ProductModel.sku, LocationModel, WarehouseModel)
            .join(ProductModel, ProductModel.id == StockModel.product_id)
            .join(LocationModel, LocationModel.id == StockModel.location_id)
            .join(WarehouseModel, WarehouseModel.id == LocationModel.warehouse_id)
            .where(
                *tenant_criteria(
                    StockModel, ProductModel, LocationModel, WarehouseModel
                ),
                WarehouseModel.branch_id == query.branch_id,
            )
        )
        if query.product_id is not None:
            statement = statement.where(StockModel.product_id == query.product_id)
        if query.page.updated_since is not None:
            statement = statement.where(
                StockModel.updated_at >= query.page.updated_since
            )
        page = paginate(
            self.session,
            statement,
            ordering(query.page, SORT_FIELDS, StockModel.id),
            query.page,
        )
        return Page(
            items=[
                {
                    "id": stock.id,
                    "product_id": stock.product_id,
                    "sku": sku,
                    "branch_id": warehouse.branch_id,
                    "warehouse_id": warehouse.id,
                    "location_id": location.id,
                    "quantity": stock.quantity,
                    "reserved": stock.reserved_quantity,
                    "available": stock.quantity - stock.reserved_quantity,
                    "updated_at": stock.updated_at,
                }
                for stock, sku, location, warehouse in page.items
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
