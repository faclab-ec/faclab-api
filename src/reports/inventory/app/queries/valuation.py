from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetInventoryValuationQuery(Query):
    warehouse_id: int | None = None
    as_of_date: date | None = None


@injectable(lifetime="scoped")
class GetInventoryValuationQueryHandler(QueryHandler[GetInventoryValuationQuery, dict]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetInventoryValuationQuery) -> dict:
        if query.as_of_date:
            items = self._valuation_at_date(query.as_of_date, query.warehouse_id)
        else:
            items = self._valuation_current(query.warehouse_id)

        total_value = sum(item["total_value"] for item in items)
        return {
            "total_value": total_value,
            "as_of_date": query.as_of_date or date.today(),
            "items": items,
        }

    def _valuation_current(self, warehouse_id: int | None) -> list[dict]:
        q = (
            self.session.query(
                ProductModel.id,
                ProductModel.name,
                ProductModel.sku,
                ProductModel.purchase_price,
                func.sum(StockModel.quantity).label("quantity"),
            )
            .join(StockModel, StockModel.product_id == ProductModel.id)
            .filter(*tenant_criteria(ProductModel, StockModel))
            .filter(ProductModel.is_service == False)  # noqa: E712
            .filter(ProductModel.purchase_price.isnot(None))
            .filter(ProductModel.purchase_price > 0)
        )
        if warehouse_id is not None:
            q = q.join(
                LocationModel, LocationModel.id == StockModel.location_id
            ).filter(
                LocationModel.warehouse_id == warehouse_id,
                *tenant_criteria(LocationModel),
            )
        q = q.group_by(
            ProductModel.id,
            ProductModel.name,
            ProductModel.sku,
            ProductModel.purchase_price,
        )
        rows = q.all()
        return [
            {
                "product_id": row.id,
                "product_name": row.name,
                "sku": row.sku,
                "quantity": row.quantity or 0,
                "average_cost": Decimal(str(row.purchase_price)),
                "total_value": Decimal(str(row.purchase_price)) * (row.quantity or 0),
            }
            for row in rows
            if (row.quantity or 0) > 0
        ]

    def _valuation_at_date(
        self, as_of_date: date, warehouse_id: int | None
    ) -> list[dict]:
        as_of_datetime = datetime.combine(as_of_date, time.max)
        q = (
            self.session.query(
                ProductModel.id,
                ProductModel.name,
                ProductModel.sku,
                ProductModel.purchase_price,
                # Quantities are signed (OUT is negative), so the sum is the net stock
                func.sum(MovementModel.quantity).label("quantity"),
            )
            .join(MovementModel, MovementModel.product_id == ProductModel.id)
            .filter(*tenant_criteria(ProductModel, MovementModel))
            .filter(ProductModel.is_service == False)  # noqa: E712
            .filter(ProductModel.purchase_price.isnot(None))
            .filter(ProductModel.purchase_price > 0)
            .filter(MovementModel.date <= as_of_datetime)
        )
        if warehouse_id is not None:
            location_ids = [
                row[0]
                for row in self.session.query(LocationModel.id)
                .filter(
                    LocationModel.warehouse_id == warehouse_id,
                    *tenant_criteria(LocationModel),
                )
                .all()
            ]
            q = q.filter(MovementModel.location_id.in_(location_ids))
        q = q.group_by(
            ProductModel.id,
            ProductModel.name,
            ProductModel.sku,
            ProductModel.purchase_price,
        )
        rows = q.all()
        return [
            {
                "product_id": row.id,
                "product_name": row.name,
                "sku": row.sku,
                "quantity": max(row.quantity or 0, 0),
                "average_cost": Decimal(str(row.purchase_price)),
                "total_value": Decimal(str(row.purchase_price))
                * max(row.quantity or 0, 0),
            }
            for row in rows
            if (row.quantity or 0) > 0
        ]
