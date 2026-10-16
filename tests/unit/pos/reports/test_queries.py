from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.pos.reports.app.queries.by_payment_method import (
    GetSalesByPaymentMethodQuery,
    GetSalesByPaymentMethodQueryHandler,
)
from src.pos.reports.app.queries.daily_summary import (
    GetDailySummaryQuery,
    GetDailySummaryQueryHandler,
)
from src.pos.reports.app.queries.x_report import GetXReportQuery, GetXReportQueryHandler
from src.pos.reports.app.queries.z_report import GetZReportQuery, GetZReportQueryHandler
from src.shared.domain.exceptions import NotFoundError


def _mock_session():
    return MagicMock()


def _mock_shift_model(
    id=1,
    cashier_name="Juan",
    opened_at=None,
    closed_at=None,
    opening_balance=Decimal("500.00"),
    closing_balance=None,
    status="OPEN",
):
    shift = MagicMock()
    shift.id = id
    shift.cashier_name = cashier_name
    shift.opened_at = opened_at or datetime(2026, 3, 14, 8, 0, 0)
    shift.closed_at = closed_at
    shift.opening_balance = opening_balance
    shift.closing_balance = closing_balance
    shift.status = status
    return shift


class TestXReport:
    def test_shift_not_found(self):
        session = _mock_session()
        session.query.return_value.filter.return_value.first.return_value = None
        handler = GetXReportQueryHandler(session)

        with pytest.raises(NotFoundError):
            handler.handle(GetXReportQuery(shift_id=999))

    def test_happy_path(self):
        session = _mock_session()
        shift = _mock_shift_model()

        # Mock query chains
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.first.return_value = shift

        # Sales aggregate
        sales_result = MagicMock()
        sales_result.count = 5
        sales_result.subtotal = Decimal("400.00")
        sales_result.tax = Decimal("60.00")
        sales_result.discount = Decimal("0")
        sales_result.total = Decimal("460.00")
        query_mock.filter.return_value = query_mock
        query_mock.one.return_value = sales_result

        # Payments
        query_mock.join.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        payment_row = MagicMock()
        payment_row.payment_method = "CASH"
        payment_row.count = 5
        payment_row.total = Decimal("460.00")
        query_mock.all.return_value = [payment_row]

        handler = GetXReportQueryHandler(session)
        result = handler._handle(GetXReportQuery(shift_id=1))

        assert "shift" in result
        assert "sales_summary" in result
        assert "payments_by_method" in result
        assert "items_sold" in result
        assert result["shift"]["id"] == 1


class TestZReport:
    def test_shift_not_found(self):
        session = _mock_session()
        session.query.return_value.filter.return_value.first.return_value = None
        x_handler = GetXReportQueryHandler(session)
        handler = GetZReportQueryHandler(session, x_handler)

        with pytest.raises(NotFoundError):
            handler.handle(GetZReportQuery(shift_id=999))

    def test_result_has_refund_and_reconciliation(self):
        session = _mock_session()
        shift = _mock_shift_model(closing_balance=Decimal("600.00"))

        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.first.return_value = shift
        query_mock.filter.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.group_by.return_value = query_mock

        # Sales agg
        sales_result = MagicMock()
        sales_result.count = 3
        sales_result.subtotal = Decimal("300.00")
        sales_result.tax = Decimal("45.00")
        sales_result.discount = Decimal("0")
        sales_result.total = Decimal("345.00")
        query_mock.one.return_value = sales_result
        query_mock.all.return_value = []

        # scalar for compute_cash_summary
        query_mock.scalar.return_value = Decimal("0")

        x_handler = GetXReportQueryHandler(session)
        handler = GetZReportQueryHandler(session, x_handler)
        result = handler._handle(GetZReportQuery(shift_id=1))

        assert "refund_summary" in result
        assert "cash_reconciliation" in result
        assert "opening_balance" in result["cash_reconciliation"]


class TestDailySummary:
    def test_happy_path(self):
        session = _mock_session()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock

        sales_result = MagicMock()
        sales_result.count = 10
        sales_result.total = Decimal("1000.00")
        query_mock.one.return_value = sales_result
        query_mock.all.return_value = []

        refund_result = MagicMock()
        refund_result.count = 1
        refund_result.total = Decimal("50.00")
        # one() called twice: sales + refunds
        query_mock.one.side_effect = [sales_result, refund_result]

        handler = GetDailySummaryQueryHandler(session)
        result = handler._handle(GetDailySummaryQuery(date=date(2026, 3, 14)))

        assert result["date"] == "2026-03-14"
        assert "total_sales" in result
        assert "total_amount" in result
        assert "payments_by_method" in result
        assert "top_products" in result
        assert "refund_summary" in result


class TestByPaymentMethod:
    def test_happy_path(self):
        session = _mock_session()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.group_by.return_value = query_mock

        row = MagicMock()
        row.payment_method = "CASH"
        row.sales_count = 10
        row.total_amount = Decimal("500.00")
        query_mock.all.return_value = [row]

        handler = GetSalesByPaymentMethodQueryHandler(session)
        result = handler._handle(GetSalesByPaymentMethodQuery())

        assert len(result) == 1
        assert result[0]["payment_method"] == "CASH"
        assert result[0]["sales_count"] == 10

    def test_with_date_filter(self):
        session = _mock_session()
        query_mock = MagicMock()
        session.query.return_value = query_mock
        query_mock.join.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.group_by.return_value = query_mock
        query_mock.all.return_value = []

        handler = GetSalesByPaymentMethodQueryHandler(session)
        result = handler._handle(
            GetSalesByPaymentMethodQuery(
                from_date=date(2026, 3, 1),
                to_date=date(2026, 3, 14),
            )
        )

        assert result == []
