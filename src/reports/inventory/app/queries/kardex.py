from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.infra.models import MovementModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.money import round_cost
from src.shared.infra.tenant import tenant_criteria


@dataclass
class GetKardexQuery(Query):
    product_id: int = 0
    warehouse_id: int | None = None
    from_date: date = field(default_factory=lambda: date.today().replace(day=1))
    to_date: date = field(default_factory=date.today)


def _balance(quantity: Decimal, value: Decimal) -> dict:
    return {
        "quantity": quantity,
        "value": value,
        "average_cost": round_cost(value / quantity) if quantity > 0 else None,
    }


@injectable(lifetime="scoped")
class GetKardexQueryHandler(QueryHandler[GetKardexQuery, dict]):
    """The valued kardex of a product (S5.6): its balance before the period,
    every movement in it with its cost and the running balance in quantity and
    value, and the closing balance. In a warehouse it takes the movements of its
    locations (a transfer between two of them is an OUT and an IN at the same
    cost); without one, every location.

    The closing balance is the opening one plus the entries minus the exits, in
    quantity and in value: each movement adds its signed quantity times the
    cost it moved at."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: GetKardexQuery) -> dict:
        product = (
            self.session.query(ProductModel.id, ProductModel.name, ProductModel.sku)
            .filter(ProductModel.id == query.product_id)
            .filter(*tenant_criteria(ProductModel))
            .first()
        )
        if product is None:
            raise NotFoundError(f"Product with id {query.product_id} not found")
        if query.warehouse_id is not None:
            warehouse = (
                self.session.query(WarehouseModel.id)
                .filter(WarehouseModel.id == query.warehouse_id)
                .filter(*tenant_criteria(WarehouseModel))
                .first()
            )
            if warehouse is None:
                raise NotFoundError(f"Warehouse with id {query.warehouse_id} not found")

        from_datetime = datetime.combine(query.from_date, time.min)
        to_datetime = datetime.combine(query.to_date, time.max)
        criteria = [
            MovementModel.product_id == query.product_id,
            *tenant_criteria(MovementModel),
        ]
        if query.warehouse_id is not None:
            criteria.append(
                MovementModel.location_id.in_(
                    select(LocationModel.id).where(
                        LocationModel.warehouse_id == query.warehouse_id,
                        *tenant_criteria(LocationModel),
                    )
                )
            )

        opening_quantity, opening_value = (
            self.session.query(
                func.coalesce(func.sum(MovementModel.quantity), 0),
                func.coalesce(
                    func.sum(MovementModel.quantity * MovementModel.unit_cost), 0
                ),
            )
            .filter(*criteria, MovementModel.date < from_datetime)
            .one()
        )
        quantity = Decimal(str(opening_quantity))
        value = Decimal(str(opening_value))
        opening = _balance(quantity, value)

        rows = (
            self.session.query(
                MovementModel.id,
                MovementModel.date,
                MovementModel.type,
                MovementModel.quantity,
                MovementModel.unit_cost,
                MovementModel.location_id,
                LocationModel.name.label("location_name"),
                MovementModel.reference_type,
                MovementModel.reference_id,
                MovementModel.reason,
            )
            .outerjoin(
                LocationModel,
                (LocationModel.id == MovementModel.location_id)
                & (LocationModel.tenant_id == MovementModel.tenant_id),
            )
            .filter(
                *criteria,
                MovementModel.date >= from_datetime,
                MovementModel.date <= to_datetime,
            )
            .order_by(MovementModel.date, MovementModel.id)
            .all()
        )

        entries = []
        in_quantity = in_value = out_quantity = out_value = Decimal(0)
        for row in rows:
            moved = Decimal(str(row.quantity))
            unit_cost = Decimal(str(row.unit_cost))
            moved_value = moved * unit_cost
            quantity += moved
            value += moved_value
            if moved > 0:
                in_quantity += moved
                in_value += moved_value
            else:
                out_quantity -= moved
                out_value -= moved_value
            balance = _balance(quantity, value)
            entries.append(
                {
                    "movement_id": row.id,
                    "date": row.date,
                    "type": MovementType(row.type).value,
                    "location_id": row.location_id,
                    "location_name": row.location_name,
                    "reference_type": row.reference_type,
                    "reference_id": row.reference_id,
                    "reason": row.reason,
                    "in_quantity": moved if moved > 0 else Decimal(0),
                    "out_quantity": -moved if moved < 0 else Decimal(0),
                    "unit_cost": unit_cost,
                    "value": abs(moved_value),
                    "balance_quantity": balance["quantity"],
                    "balance_value": balance["value"],
                    "average_cost": balance["average_cost"],
                }
            )

        return {
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "warehouse_id": query.warehouse_id,
            "from_date": query.from_date,
            "to_date": query.to_date,
            "opening": opening,
            "entries": entries,
            "total_in": {"quantity": in_quantity, "value": in_value},
            "total_out": {"quantity": out_quantity, "value": out_value},
            "closing": _balance(quantity, value),
        }
