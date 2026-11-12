from src.reports.inventory.app.queries.kardex import GetKardexQueryHandler
from src.reports.inventory.app.queries.movement_history import (
    GetMovementHistoryReportQueryHandler,
)
from src.reports.inventory.app.queries.rotation import GetProductRotationQueryHandler
from src.reports.inventory.app.queries.valuation import (
    GetInventoryValuationQueryHandler,
)
from src.reports.inventory.app.queries.warehouse_summary import (
    GetWarehouseSummaryQueryHandler,
)

REPORT_INJECTABLES = [
    GetInventoryValuationQueryHandler,
    GetProductRotationQueryHandler,
    GetMovementHistoryReportQueryHandler,
    GetWarehouseSummaryQueryHandler,
    GetKardexQueryHandler,
]
