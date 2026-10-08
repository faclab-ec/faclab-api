import dataclasses
from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.inventory.alert.domain.types import AlertType, StockAlert
from src.inventory.lot.app.repositories import LotRepository
from src.inventory.lot.domain.specifications import ExpiringLots
from src.inventory.stock.app.repositories import StockRepository
from src.inventory.stock.domain.specifications import (
    LowStockProducts,
    OutOfStockProducts,
    ReorderPointProducts,
)
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetLowStockAlertsQuery(Query):
    warehouse_id: int | None = None


@injectable(lifetime="scoped")
class GetLowStockAlertsQueryHandler(QueryHandler[GetLowStockAlertsQuery, list[dict]]):
    def __init__(
        self,
        stock_repo: StockRepository,
        product_repo: ProductRepository,
    ):
        self.stock_repo = stock_repo
        self.product_repo = product_repo

    def _handle(self, query: GetLowStockAlertsQuery) -> list[dict]:
        spec = LowStockProducts(warehouse_id=query.warehouse_id)
        stocks = self.stock_repo.filter_by_spec(spec)

        alerts = []
        for stock in stocks:
            product = self.product_repo.get_by_id(stock.product_id)
            if product is None or product.is_service:
                continue
            alert = StockAlert(
                type=AlertType.LOW_STOCK,
                product_id=product.require_id(),
                product_name=product.name,
                sku=product.sku,
                current_quantity=stock.quantity,
                threshold=product.min_stock,
                warehouse_id=query.warehouse_id,
            )
            alerts.append(dataclasses.asdict(alert))
        return alerts


@dataclass
class GetOutOfStockAlertsQuery(Query):
    warehouse_id: int | None = None


@injectable(lifetime="scoped")
class GetOutOfStockAlertsQueryHandler(
    QueryHandler[GetOutOfStockAlertsQuery, list[dict]]
):
    def __init__(
        self,
        stock_repo: StockRepository,
        product_repo: ProductRepository,
    ):
        self.stock_repo = stock_repo
        self.product_repo = product_repo

    def _handle(self, query: GetOutOfStockAlertsQuery) -> list[dict]:
        spec = OutOfStockProducts(warehouse_id=query.warehouse_id)
        stocks = self.stock_repo.filter_by_spec(spec)

        alerts = []
        for stock in stocks:
            product = self.product_repo.get_by_id(stock.product_id)
            if product is None or product.is_service:
                continue
            alert = StockAlert(
                type=AlertType.OUT_OF_STOCK,
                product_id=product.require_id(),
                product_name=product.name,
                sku=product.sku,
                current_quantity=0,
                threshold=0,
                warehouse_id=query.warehouse_id,
            )
            alerts.append(dataclasses.asdict(alert))
        return alerts


@dataclass
class GetReorderPointAlertsQuery(Query):
    warehouse_id: int | None = None


@injectable(lifetime="scoped")
class GetReorderPointAlertsQueryHandler(
    QueryHandler[GetReorderPointAlertsQuery, list[dict]]
):
    def __init__(
        self,
        stock_repo: StockRepository,
        product_repo: ProductRepository,
    ):
        self.stock_repo = stock_repo
        self.product_repo = product_repo

    def _handle(self, query: GetReorderPointAlertsQuery) -> list[dict]:
        spec = ReorderPointProducts(warehouse_id=query.warehouse_id)
        stocks = self.stock_repo.filter_by_spec(spec)

        alerts = []
        for stock in stocks:
            product = self.product_repo.get_by_id(stock.product_id)
            if product is None or product.is_service:
                continue
            alert = StockAlert(
                type=AlertType.REORDER_POINT,
                product_id=product.require_id(),
                product_name=product.name,
                sku=product.sku,
                current_quantity=stock.quantity,
                threshold=product.reorder_point,
                warehouse_id=query.warehouse_id,
            )
            alerts.append(dataclasses.asdict(alert))
        return alerts


@dataclass
class GetExpiringLotsAlertsQuery(Query):
    days: int = 30


@injectable(lifetime="scoped")
class GetExpiringLotsAlertsQueryHandler(
    QueryHandler[GetExpiringLotsAlertsQuery, list[dict]]
):
    def __init__(
        self,
        lot_repo: LotRepository,
        product_repo: ProductRepository,
    ):
        self.lot_repo = lot_repo
        self.product_repo = product_repo

    def _handle(self, query: GetExpiringLotsAlertsQuery) -> list[dict]:
        spec = ExpiringLots(days=query.days)
        lots = self.lot_repo.filter_by_spec(spec)

        alerts = []
        for lot in lots:
            product = self.product_repo.get_by_id(lot.product_id)
            if product is None or product.is_service:
                continue
            alert = StockAlert(
                type=AlertType.EXPIRING_SOON,
                product_id=product.require_id(),
                product_name=product.name,
                sku=product.sku,
                current_quantity=lot.current_quantity,
                threshold=0,
                lot_id=lot.id,
                days_to_expiry=lot.days_to_expiry,
            )
            alerts.append(dataclasses.asdict(alert))
        return alerts
