from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetWarehouseSummaryQuery(Query):
    warehouse_id: int | None = None


@injectable(lifetime="scoped")
class GetWarehouseSummaryQueryHandler(
    QueryHandler[GetWarehouseSummaryQuery, list[dict]]
):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetWarehouseSummaryQuery) -> list[dict]:
        q = (
            self.session.query(
                WarehouseModel.id,
                WarehouseModel.name,
                WarehouseModel.code,
                func.count(func.distinct(StockModel.product_id)).label(
                    "total_products"
                ),
                func.coalesce(func.sum(StockModel.quantity), 0).label("total_quantity"),
                func.coalesce(func.sum(StockModel.reserved_quantity), 0).label(
                    "reserved_quantity"
                ),
                func.coalesce(
                    func.sum(
                        StockModel.quantity
                        * func.coalesce(ProductModel.purchase_price, 0)
                    ),
                    0,
                ).label("total_value"),
            )
            .join(LocationModel, LocationModel.warehouse_id == WarehouseModel.id)
            .join(StockModel, StockModel.location_id == LocationModel.id)
            .join(ProductModel, ProductModel.id == StockModel.product_id)
            .filter(
                *tenant_criteria(
                    WarehouseModel, LocationModel, StockModel, ProductModel
                )
            )
            .filter(WarehouseModel.is_active == True)  # noqa: E712
            .filter(ProductModel.is_service == False)  # noqa: E712
            .filter(StockModel.quantity > 0)
            .group_by(WarehouseModel.id, WarehouseModel.name, WarehouseModel.code)
        )
        if query.warehouse_id is not None:
            q = q.filter(WarehouseModel.id == query.warehouse_id)

        rows = q.all()
        return [
            {
                "warehouse_id": row.id,
                "warehouse_name": row.name,
                "warehouse_code": row.code,
                "total_products": row.total_products or 0,
                "total_quantity": row.total_quantity or 0,
                "reserved_quantity": row.reserved_quantity or 0,
                "available_quantity": (row.total_quantity or 0)
                - (row.reserved_quantity or 0),
                "total_value": Decimal(str(row.total_value or 0)),
            }
            for row in rows
        ]
