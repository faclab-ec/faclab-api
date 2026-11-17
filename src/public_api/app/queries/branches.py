from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from wireup import injectable

from src.inventory.location.infra.models import LocationModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.organization.infra.models import BranchModel, EmissionPointModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class ListApiBranchesQuery(Query):
    # The client's branches; None, every one of the tenant
    branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class ListApiBranchesQueryHandler(QueryHandler[ListApiBranchesQuery, list[dict]]):
    """The active branches the client may operate in, each with its active
    emission points and the active locations of its active warehouses: what a
    sale of the API names (`emissionPointId`, `locationId`)"""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListApiBranchesQuery) -> list[dict]:
        statement = select(BranchModel).where(
            *tenant_criteria(BranchModel), BranchModel.is_active.is_(True)
        )
        if query.branch_ids is not None:
            statement = statement.where(BranchModel.id.in_(query.branch_ids))
        branches = list(self.session.scalars(statement.order_by(BranchModel.id)))
        ids = [branch.id for branch in branches]
        points = self._emission_points(ids)
        locations = self._locations(ids)
        return [
            {
                "id": branch.id,
                "code": branch.establishment_code,
                "name": branch.name,
                "address": branch.address,
                "is_main": branch.is_main,
                "emission_points": points.get(branch.id, []),
                "locations": locations.get(branch.id, []),
            }
            for branch in branches
        ]

    def _emission_points(self, branch_ids: list[int]) -> dict[int, list[dict]]:
        rows = self.session.scalars(
            select(EmissionPointModel)
            .where(
                *tenant_criteria(EmissionPointModel),
                EmissionPointModel.branch_id.in_(branch_ids),
                EmissionPointModel.is_active.is_(True),
            )
            .order_by(EmissionPointModel.code, EmissionPointModel.id)
        )
        found: dict[int, list[dict]] = {}
        for point in rows:
            found.setdefault(point.branch_id, []).append(
                {"id": point.id, "code": point.code, "name": point.name}
            )
        return found

    def _locations(self, branch_ids: list[int]) -> dict[int, list[dict]]:
        rows = self.session.execute(
            select(LocationModel, WarehouseModel)
            .join(WarehouseModel, WarehouseModel.id == LocationModel.warehouse_id)
            .where(
                *tenant_criteria(LocationModel, WarehouseModel),
                WarehouseModel.branch_id.in_(branch_ids),
                WarehouseModel.is_active.is_(True),
                LocationModel.is_active.is_(True),
            )
            .order_by(WarehouseModel.code, LocationModel.code, LocationModel.id)
        )
        found: dict[int, list[dict]] = {}
        for location, warehouse in rows:
            found.setdefault(warehouse.branch_id, []).append(
                {
                    "id": location.id,
                    "code": location.code,
                    "name": location.name,
                    "warehouse_id": warehouse.id,
                    "warehouse_code": warehouse.code,
                    "warehouse_name": warehouse.name,
                }
            )
        return found
