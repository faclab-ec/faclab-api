from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.money import round_cost
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetInventoryValuationQuery(Query):
    warehouse_id: int | None = None
    as_of_date: date | None = None


def _item(row) -> dict:
    """A product's quantity and value; its average cost is value / quantity,
    weighted across the locations it is in (S5.6)"""
    quantity = Decimal(str(row.quantity or 0))
    value = Decimal(str(row.value or 0))
    return {
        "product_id": row.id,
        "product_name": row.name,
        "sku": row.sku,
        "quantity": quantity,
        "average_cost": round_cost(value / quantity),
        "total_value": value,
    }


@injectable(lifetime="scoped")
class GetInventoryValuationQueryHandler(QueryHandler[GetInventoryValuationQuery, dict]):
    """Inventory at its weighted average cost (S5.6): today from the stock rows
    (quantity × the average of each location), at a date from the movements up
    to it (quantity × the cost each one moved at). Both add up to the same
    value: every IN enters at the cost it recalculates the average with and
    every OUT leaves at that average."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetInventoryValuationQuery) -> dict:
        if query.as_of_date:
            items = self._valuation_at_date(query.as_of_date, query.warehouse_id)
        else:
            items = self._valuation_current(query.warehouse_id)

        total_value = sum((item["total_value"] for item in items), Decimal(0))
        return {
            "total_value": total_value,
            "as_of_date": query.as_of_date or date.today(),
            "items": items,
        }

    def _locations_of(self, warehouse_id: int):
        return select(LocationModel.id).where(
            LocationModel.warehouse_id == warehouse_id,
            *tenant_criteria(LocationModel),
        )

    def _valuation_current(self, warehouse_id: int | None) -> list[dict]:
        q = (
            self.session.query(
                ProductModel.id,
                ProductModel.name,
                ProductModel.sku,
                func.sum(StockModel.quantity).label("quantity"),
                func.sum(StockModel.quantity * StockModel.average_cost).label("value"),
            )
            .join(StockModel, StockModel.product_id == ProductModel.id)
            .filter(*tenant_criteria(ProductModel, StockModel))
            .filter(ProductModel.is_service == False)  # noqa: E712
        )
        if warehouse_id is not None:
            q = q.filter(StockModel.location_id.in_(self._locations_of(warehouse_id)))
        q = q.group_by(ProductModel.id, ProductModel.name, ProductModel.sku)
        return [_item(row) for row in q.all() if (row.quantity or 0) > 0]

    def _valuation_at_date(
        self, as_of_date: date, warehouse_id: int | None
    ) -> list[dict]:
        as_of_datetime = datetime.combine(as_of_date, time.max)
        q = (
            self.session.query(
                ProductModel.id,
                ProductModel.name,
                ProductModel.sku,
                # Quantities are signed (OUT is negative), so the sums are the
                # net stock and its value
                func.sum(MovementModel.quantity).label("quantity"),
                func.sum(MovementModel.quantity * MovementModel.unit_cost).label(
                    "value"
                ),
            )
            .join(MovementModel, MovementModel.product_id == ProductModel.id)
            .filter(*tenant_criteria(ProductModel, MovementModel))
            .filter(ProductModel.is_service == False)  # noqa: E712
            .filter(MovementModel.date <= as_of_datetime)
        )
        if warehouse_id is not None:
            q = q.filter(
                MovementModel.location_id.in_(self._locations_of(warehouse_id))
            )
        q = q.group_by(ProductModel.id, ProductModel.name, ProductModel.sku)
        return [_item(row) for row in q.all() if (row.quantity or 0) > 0]
