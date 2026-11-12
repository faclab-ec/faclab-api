from src.inventory.stock.app.costs import InventoryCosts
from src.inventory.stock.app.queries.stock import (
    GetAllStocksQueryHandler,
    GetStockByIdQueryHandler,
    GetStockByProductQueryHandler,
)
from src.inventory.stock.infra.mappers import StockMapper
from src.inventory.stock.infra.repositories import SqlAlchemyStockRepository

INJECTABLES = [
    InventoryCosts,
    StockMapper,
    SqlAlchemyStockRepository,
    GetAllStocksQueryHandler,
    GetStockByIdQueryHandler,
    GetStockByProductQueryHandler,
]
