from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.inventory.location.app.repositories import LocationRepository
from src.inventory.stock.app.repositories import StockRepository
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllStocksQuery(Query):
    """Query para obtener todos los stocks con filtros opcionales"""

    product_id: int | None = None
    location_id: int | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllStocksQueryHandler(QueryHandler[GetAllStocksQuery, dict]):
    def __init__(
        self,
        repo: StockRepository,
        product_repo: ProductRepository,
        location_repo: LocationRepository,
    ):
        self.repo = repo
        self.product_repo = product_repo
        self.location_repo = location_repo

    def _handle(self, query: GetAllStocksQuery) -> dict:
        filter_kwargs = {}
        if query.product_id is not None:
            filter_kwargs["product_id"] = query.product_id
        if query.location_id is not None:
            filter_kwargs["location_id"] = query.location_id
        result = self.repo.paginate(
            limit=query.limit, offset=query.offset, **filter_kwargs
        )

        items = result["items"]
        product_names = {
            p.id: p.name
            for p in self.product_repo.get_by_ids(s["product_id"] for s in items)
        }
        location_names = {
            loc.id: loc.name
            for loc in self.location_repo.get_by_ids(
                s["location_id"] for s in items if s["location_id"] is not None
            )
        }
        for item in items:
            item["product_name"] = product_names.get(item["product_id"])
            item["location_name"] = location_names.get(item["location_id"])
        return result


@dataclass
class GetStockByIdQuery(Query):
    """Query para obtener un stock por su ID"""

    id: int = 0


@injectable(lifetime="scoped")
class GetStockByIdQueryHandler(QueryHandler[GetStockByIdQuery, dict]):
    def __init__(self, repo: StockRepository):
        self.repo = repo

    def _handle(self, query: GetStockByIdQuery) -> dict:
        stock = self.repo.get_by_id(query.id)
        if stock is None:
            raise NotFoundError(f"Stock with id {query.id} not found")
        return stock.dict()


@dataclass
class GetStockByProductQuery(Query):
    """Query para obtener el stock de un producto específico"""

    product_id: int = 0


@injectable(lifetime="scoped")
class GetStockByProductQueryHandler(QueryHandler[GetStockByProductQuery, dict]):
    def __init__(self, repo: StockRepository):
        self.repo = repo

    def _handle(self, query: GetStockByProductQuery) -> dict:
        stock = self.repo.first(product_id=query.product_id)
        if stock is None:
            raise NotFoundError(f"Stock for product_id {query.product_id} not found")
        return stock.dict()
