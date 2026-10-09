from decimal import Decimal
from unittest.mock import MagicMock

from src.reports.dashboard.app.queries.dashboard import (
    GetDashboardQuery,
    GetDashboardQueryHandler,
)


def _handler(**results) -> tuple[GetDashboardQueryHandler, dict[str, MagicMock]]:
    handlers = {
        name: MagicMock()
        for name in (
            "valuation",
            "warehouse_summary",
            "low_stock",
            "out_of_stock",
            "reorder_point",
            "expiring_lots",
            "sale_repo",
        )
    }
    for name, value in results.items():
        handlers[name].handle.return_value = value
    handlers["sale_repo"].count_by.return_value = 4
    return GetDashboardQueryHandler(**handlers), handlers


def test_dashboard_returns_totals_instead_of_full_lists():
    handler, handlers = _handler(
        valuation={"total_value": Decimal("1250.50"), "items": [{}] * 40},
        warehouse_summary=[{"warehouse_id": 1}],
        low_stock=[{}, {}],
        out_of_stock=[{}],
        reorder_point=[],
        expiring_lots=[{}, {}, {}],
    )

    result = handler.handle(GetDashboardQuery(expiring_days=15))

    assert result == {
        "inventory_value": Decimal("1250.50"),
        "warehouses": [{"warehouse_id": 1}],
        "alerts": {
            "low_stock": 2,
            "out_of_stock": 1,
            "reorder_point": 0,
            "expiring_soon": 3,
        },
        "uninvoiced_sales": 4,
    }
    assert handlers["expiring_lots"].handle.call_args.args[0].days == 15
    handlers["sale_repo"].count_by.assert_called_once_with(status="CONFIRMED")
