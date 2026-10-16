from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.infra.models import MovementModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetMovementHistoryReportQuery(Query):
    product_id: int | None = None
    type: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    warehouse_id: int | None = None
    limit: int = 50
    offset: int = 0


@injectable(lifetime="scoped")
class GetMovementHistoryReportQueryHandler(
    QueryHandler[GetMovementHistoryReportQuery, dict]
):
    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetMovementHistoryReportQuery) -> dict:
        q = self.session.query(
            MovementModel.id,
            MovementModel.product_id,
            ProductModel.name.label("product_name"),
            ProductModel.sku,
            MovementModel.quantity,
            MovementModel.type,
            MovementModel.location_id,
            MovementModel.source_location_id,
            MovementModel.reference_type,
            MovementModel.reference_id,
            MovementModel.reason,
            MovementModel.date,
            MovementModel.created_at,
        ).join(ProductModel, ProductModel.id == MovementModel.product_id)
        q = q.filter(*tenant_criteria(MovementModel, ProductModel))

        if query.product_id is not None:
            q = q.filter(MovementModel.product_id == query.product_id)
        if query.type is not None:
            q = q.filter(MovementModel.type == query.type)
        if query.from_date is not None:
            q = q.filter(
                MovementModel.date >= datetime.combine(query.from_date, time.min)
            )
        if query.to_date is not None:
            q = q.filter(
                MovementModel.date <= datetime.combine(query.to_date, time.max)
            )
        if query.warehouse_id is not None:
            location_subq = select(LocationModel.id).where(
                LocationModel.warehouse_id == query.warehouse_id,
                *tenant_criteria(LocationModel),
            )
            q = q.filter(MovementModel.location_id.in_(location_subq))

        total = q.count()
        rows = (
            q.order_by(MovementModel.date.desc())
            .offset(query.offset)
            .limit(query.limit)
            .all()
        )

        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": [
                {
                    "id": row.id,
                    "product_id": row.product_id,
                    "product_name": row.product_name,
                    "sku": row.sku,
                    "quantity": row.quantity,
                    "type": row.type,
                    "location_id": row.location_id,
                    "source_location_id": row.source_location_id,
                    "reference_type": row.reference_type,
                    "reference_id": row.reference_id,
                    "reason": row.reason,
                    "date": row.date,
                    "created_at": row.created_at,
                }
                for row in rows
            ],
        }
