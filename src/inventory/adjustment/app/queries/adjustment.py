from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.product_names import with_product_names
from src.catalog.product.app.repositories import ProductRepository
from src.inventory.adjustment.app.repositories import (
    AdjustmentItemRepository,
    InventoryAdjustmentRepository,
)
from src.inventory.adjustment.domain.specifications import (
    AdjustmentsByStatus,
    AdjustmentsByWarehouse,
)
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllAdjustmentsQuery(Query):
    status: str | None = None
    warehouse_id: int | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllAdjustmentsQueryHandler(QueryHandler[GetAllAdjustmentsQuery, dict]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, query: GetAllAdjustmentsQuery) -> dict:
        from src.inventory.adjustment.domain.entities import AdjustmentStatus

        spec = None

        if query.status is not None:
            status_spec = AdjustmentsByStatus(AdjustmentStatus(query.status))
            spec = status_spec if spec is None else spec & status_spec

        if query.warehouse_id is not None:
            warehouse_spec = AdjustmentsByWarehouse(query.warehouse_id)
            spec = warehouse_spec if spec is None else spec & warehouse_spec

        if spec is not None:
            return self.repo.paginate_by_spec(
                spec, limit=query.limit, offset=query.offset
            )
        return self.repo.paginate(limit=query.limit, offset=query.offset)


@dataclass
class GetAdjustmentByIdQuery(Query):
    id: int = 0


@injectable(lifetime="scoped")
class GetAdjustmentByIdQueryHandler(QueryHandler[GetAdjustmentByIdQuery, dict]):
    def __init__(self, repo: InventoryAdjustmentRepository):
        self.repo = repo

    def _handle(self, query: GetAdjustmentByIdQuery) -> dict:
        adjustment = self.repo.get_by_id(query.id)
        if adjustment is None:
            raise NotFoundError(f"Adjustment with id {query.id} not found")
        return adjustment.dict()


@dataclass
class GetAdjustmentItemsQuery(Query):
    adjustment_id: int = 0


@injectable(lifetime="scoped")
class GetAdjustmentItemsQueryHandler(QueryHandler[GetAdjustmentItemsQuery, list[dict]]):
    def __init__(
        self, item_repo: AdjustmentItemRepository, product_repo: ProductRepository
    ):
        self.item_repo = item_repo
        self.product_repo = product_repo

    def _handle(self, query: GetAdjustmentItemsQuery) -> list[dict]:
        items = self.item_repo.filter_by(adjustment_id=query.adjustment_id)
        return with_product_names(
            [{**item.dict(), "difference": item.difference} for item in items],
            self.product_repo,
        )
