from dataclasses import dataclass

from wireup import injectable

from src.customers.app.repositories import CustomerRepository
from src.sales.app.repositories import SaleRepository
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class GetAllSalesQuery(Query):
    """Query para obtener todas las ventas con filtros opcionales"""

    customer_id: int | None = None
    status: str | None = None
    invoice_status: str | None = None
    limit: int | None = None
    offset: int | None = None


@injectable(lifetime="scoped")
class GetAllSalesQueryHandler(QueryHandler[GetAllSalesQuery, dict]):
    """Handler para obtener todas las ventas"""

    def __init__(self, repo: SaleRepository, customer_repo: CustomerRepository):
        self.repo = repo
        self.customer_repo = customer_repo

    def _handle(self, query: GetAllSalesQuery) -> dict:
        """Obtiene las ventas con los filtros especificados"""
        filters = {}
        if query.customer_id is not None:
            filters["customer_id"] = query.customer_id
        if query.status is not None:
            filters["status"] = query.status
        if query.invoice_status is not None:
            filters["invoice_status"] = query.invoice_status
        result = self.repo.paginate(limit=query.limit, offset=query.offset, **filters)

        customer_names = {
            c.id: c.name
            for c in self.customer_repo.get_by_ids(
                s["customer_id"]
                for s in result["items"]
                if s["customer_id"] is not None
            )
        }
        for sale in result["items"]:
            sale["customer_name"] = customer_names.get(sale["customer_id"])
        return result


@dataclass
class GetSaleByIdQuery(Query):
    """Query para obtener una venta por ID"""

    sale_id: int


@injectable(lifetime="scoped")
class GetSaleByIdQueryHandler(QueryHandler[GetSaleByIdQuery, dict]):
    """Handler para obtener una venta por ID"""

    def __init__(self, repo: SaleRepository, customer_repo: CustomerRepository):
        self.repo = repo
        self.customer_repo = customer_repo

    def _handle(self, query: GetSaleByIdQuery) -> dict:
        """Obtiene una venta específica por ID"""
        sale = self.repo.get_by_id(query.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {query.sale_id} not found")
        customer = (
            self.customer_repo.get_by_id(sale.customer_id)
            if sale.customer_id is not None
            else None
        )
        return {**sale.dict(), "customer_name": customer.name if customer else None}
