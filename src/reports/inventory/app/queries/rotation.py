from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.stock.infra.models import StockModel
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetProductRotationQuery(Query):
    from_date: date = field(default_factory=lambda: date.today().replace(day=1))
    to_date: date = field(default_factory=date.today)
    warehouse_id: int | None = None


@injectable(lifetime="scoped")
class GetProductRotationQueryHandler(QueryHandler[GetProductRotationQuery, list[dict]]):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetProductRotationQuery) -> list[dict]:
        from_datetime = datetime.combine(query.from_date, time.min)
        to_datetime = datetime.combine(query.to_date, time.max)
        days_in_period = max((query.to_date - query.from_date).days + 1, 1)

        movement_rows = self._fetch_movement_aggregates(
            from_datetime, to_datetime, query.warehouse_id
        )
        stock_by_product = self._fetch_current_stocks(query.warehouse_id)

        results = []
        for row in movement_rows:
            current_stock = stock_by_product.get(row.product_id, 0) or 0
            total_out = row.total_out or 0
            total_in = row.total_in or 0

            turnover_rate = Decimal("0")
            if current_stock > 0 and total_out > 0:
                turnover_rate = Decimal(str(total_out)) / Decimal(str(current_stock))

            days_of_stock = None
            if total_out > 0 and current_stock > 0:
                daily_out = total_out / days_in_period
                if daily_out > 0:
                    days_of_stock = int(current_stock / daily_out)

            results.append(
                {
                    "product_id": row.product_id,
                    "product_name": row.product_name,
                    "sku": row.sku,
                    "total_in": total_in,
                    "total_out": total_out,
                    "current_stock": current_stock,
                    "turnover_rate": turnover_rate,
                    "days_of_stock": days_of_stock,
                }
            )

        return results

    def _fetch_movement_aggregates(
        self,
        from_datetime: datetime,
        to_datetime: datetime,
        warehouse_id: int | None,
    ) -> list:
        q = (
            self.session.query(
                MovementModel.product_id,
                ProductModel.name.label("product_name"),
                ProductModel.sku,
                func.sum(
                    case(
                        (MovementModel.type == MovementType.IN, MovementModel.quantity),
                        else_=0,
                    )
                ).label("total_in"),
                # OUT movements are stored with negative quantities
                func.sum(
                    case(
                        (
                            MovementModel.type == MovementType.OUT,
                            -MovementModel.quantity,
                        ),
                        else_=0,
                    )
                ).label("total_out"),
            )
            .join(ProductModel, ProductModel.id == MovementModel.product_id)
            .filter(MovementModel.date >= from_datetime)
            .filter(MovementModel.date <= to_datetime)
            .filter(ProductModel.is_service == False)  # noqa: E712
        )
        if warehouse_id is not None:
            location_subq = select(LocationModel.id).where(
                LocationModel.warehouse_id == warehouse_id
            )
            q = q.filter(MovementModel.location_id.in_(location_subq))
        return q.group_by(
            MovementModel.product_id, ProductModel.name, ProductModel.sku
        ).all()

    def _fetch_current_stocks(self, warehouse_id: int | None) -> dict[int, int]:
        q = self.session.query(
            StockModel.product_id,
            func.sum(StockModel.quantity).label("current_stock"),
        )
        if warehouse_id is not None:
            q = q.join(
                LocationModel, LocationModel.id == StockModel.location_id
            ).filter(LocationModel.warehouse_id == warehouse_id)
        rows = q.group_by(StockModel.product_id).all()
        return {row.product_id: row.current_stock or 0 for row in rows}
