from dataclasses import dataclass

from wireup import injectable

from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllWarehousesQuery(Query):
    branch_id: int | None = None
    is_active: bool | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllWarehousesQueryHandler(QueryHandler[GetAllWarehousesQuery, dict]):
    def __init__(self, repo: WarehouseRepository):
        self.repo = repo

    def _handle(self, query: GetAllWarehousesQuery) -> dict:
        filters: dict = {}
        if query.branch_id is not None:
            filters["branch_id"] = query.branch_id
        if query.is_active is not None:
            filters["is_active"] = query.is_active
        return self.repo.paginate(limit=query.limit, offset=query.offset, **filters)


@dataclass
class GetWarehouseByIdQuery(Query):
    warehouse_id: int


@injectable(lifetime="scoped")
class GetWarehouseByIdQueryHandler(QueryHandler[GetWarehouseByIdQuery, dict]):
    def __init__(self, repo: WarehouseRepository):
        self.repo = repo

    def _handle(self, query: GetWarehouseByIdQuery) -> dict:
        warehouse = self.repo.get_by_id(query.warehouse_id)
        if warehouse is None:
            raise NotFoundError(f"Warehouse {query.warehouse_id} not found")
        return warehouse.dict()
