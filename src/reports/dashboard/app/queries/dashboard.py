from dataclasses import dataclass

from wireup import injectable

from src.inventory.alert.app.queries.alerts import (
    GetExpiringLotsAlertsQuery,
    GetExpiringLotsAlertsQueryHandler,
    GetLowStockAlertsQuery,
    GetLowStockAlertsQueryHandler,
    GetOutOfStockAlertsQuery,
    GetOutOfStockAlertsQueryHandler,
    GetReorderPointAlertsQuery,
    GetReorderPointAlertsQueryHandler,
)
from src.reports.inventory.app.queries.valuation import (
    GetInventoryValuationQuery,
    GetInventoryValuationQueryHandler,
)
from src.reports.inventory.app.queries.warehouse_summary import (
    GetWarehouseSummaryQuery,
    GetWarehouseSummaryQueryHandler,
)
from src.shared.app.queries import Query, QueryHandler


@dataclass
class GetDashboardQuery(Query):
    expiring_days: int = 30


@injectable(lifetime="scoped")
class GetDashboardQueryHandler(QueryHandler[GetDashboardQuery, dict]):
    """Lo que muestra la página de inicio, en una sola llamada.

    Reúne el valor del inventario, el resumen por almacén y cuántas alertas hay
    de cada tipo; la web hacía seis llamadas y descargaba la valoración y las
    alertas completas solo para mostrar totales.
    """

    def __init__(
        self,
        valuation: GetInventoryValuationQueryHandler,
        warehouse_summary: GetWarehouseSummaryQueryHandler,
        low_stock: GetLowStockAlertsQueryHandler,
        out_of_stock: GetOutOfStockAlertsQueryHandler,
        reorder_point: GetReorderPointAlertsQueryHandler,
        expiring_lots: GetExpiringLotsAlertsQueryHandler,
    ):
        self.valuation = valuation
        self.warehouse_summary = warehouse_summary
        self.low_stock = low_stock
        self.out_of_stock = out_of_stock
        self.reorder_point = reorder_point
        self.expiring_lots = expiring_lots

    def _handle(self, query: GetDashboardQuery) -> dict:
        valuation = self.valuation.handle(GetInventoryValuationQuery())
        return {
            "inventory_value": valuation["total_value"],
            "warehouses": self.warehouse_summary.handle(GetWarehouseSummaryQuery()),
            "alerts": {
                "low_stock": len(self.low_stock.handle(GetLowStockAlertsQuery())),
                "out_of_stock": len(
                    self.out_of_stock.handle(GetOutOfStockAlertsQuery())
                ),
                "reorder_point": len(
                    self.reorder_point.handle(GetReorderPointAlertsQuery())
                ),
                "expiring_soon": len(
                    self.expiring_lots.handle(
                        GetExpiringLotsAlertsQuery(days=query.expiring_days)
                    )
                ),
            },
        }
