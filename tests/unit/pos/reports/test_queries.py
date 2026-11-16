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
from src.pos.shift.domain.closing import (
    ItemSold,
    MethodTotal,
    ShiftClosingLine,
    ShiftTotals,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.exceptions import NotFoundError
from tests.unit.pos.closings import FakeShiftTotals, InMemoryShiftClosings, make_closing


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


def _session_with(shift) -> MagicMock:
    """A session whose shift lookup (`get_shift`) finds `shift`"""
    session = _mock_session()
    session.query.return_value.filter.return_value.first.return_value = shift
    return session


_TOTALS = ShiftTotals(
    sales_count=5,
    sales_subtotal=Decimal("400.00"),
    sales_tax=Decimal("60.00"),
    sales_total=Decimal("460.00"),
    payments=[
        MethodTotal("CASH", 4, Decimal("400.00")),
        MethodTotal("CREDIT_CARD", 1, Decimal("60.00")),
    ],
    refunds_count=1,
    refunds_total=Decimal("20.00"),
    refund_payments=[MethodTotal("CASH", 1, Decimal("20.00"))],
    items_sold=[ItemSold("Martillo", "MAR-01", Decimal("3"), Decimal("460.00"))],
)


class TestXReport:
    def test_shift_not_found(self):
        handler = GetXReportQueryHandler(_session_with(None), FakeShiftTotals())

        with pytest.raises(NotFoundError):
            handler.handle(GetXReportQuery(shift_id=999))

    def test_happy_path(self):
        handler = GetXReportQueryHandler(
            _session_with(_mock_shift_model()), FakeShiftTotals(_TOTALS)
        )

        result = handler.handle(GetXReportQuery(shift_id=1))

        assert result["shift"]["id"] == 1
        assert result["sales_summary"]["total"] == Decimal("460.00")
        assert result["payments_by_method"] == [
            {"payment_method": "CASH", "count": 4, "total": Decimal("400.00")},
            {"payment_method": "CREDIT_CARD", "count": 1, "total": Decimal("60.00")},
        ]
        assert result["items_sold"][0]["sku"] == "MAR-01"


class TestZReport:
    def test_shift_not_found(self):
        handler = GetZReportQueryHandler(
            _session_with(None), FakeShiftTotals(), InMemoryShiftClosings()
        )

        with pytest.raises(NotFoundError):
            handler.handle(GetZReportQuery(shift_id=999))

    def test_an_open_shift_is_calculated_without_a_closing(self):
        handler = GetZReportQueryHandler(
            _session_with(_mock_shift_model()),
            FakeShiftTotals(_TOTALS),
            InMemoryShiftClosings(),
        )

        result = handler.handle(GetZReportQuery(shift_id=1))

        assert result["closing"] is None
        assert result["refund_summary"] == {"count": 1, "total": Decimal("20.00")}
        # 500 + 400 - 20
        assert result["cash_reconciliation"]["expected_balance"] == Decimal("880.00")
        assert result["cash_reconciliation"]["discrepancy"] is None

    def test_a_shift_closed_before_s5_9_is_calculated_with_its_count(self):
        handler = GetZReportQueryHandler(
            _session_with(
                _mock_shift_model(status="CLOSED", closing_balance=Decimal("870.00"))
            ),
            FakeShiftTotals(_TOTALS),
            InMemoryShiftClosings(),
        )

        result = handler.handle(GetZReportQuery(shift_id=1))

        assert result["closing"] is None
        assert result["cash_reconciliation"]["discrepancy"] == Decimal("-10.00")

    def test_a_shift_with_its_z_closing_answers_what_the_closing_kept(self):
        """S5.9: the totals moved after the closing (they say 460 sold), the Z
        report doesn't: it reads the closing"""
        closing = make_closing(
            sales_count=2,
            sales_total=Decimal("100.00"),
            cash_sales=Decimal("100.00"),
            refunds_count=0,
            justification_threshold=Decimal("1.00"),
            items_sold=[ItemSold("Clavo", "CLA-01", Decimal("10"), Decimal("100.00"))],
            lines=[
                ShiftClosingLine(
                    payment_method=PaymentMethod.CASH,
                    payments_count=2,
                    payments_total=Decimal("100.00"),
                    expected=Decimal("600.00"),
                    counted=Decimal("595.00"),
                    difference=Decimal("-5.00"),
                    justification="Faltante",
                ),
                ShiftClosingLine(
                    payment_method=PaymentMethod.CREDIT,
                    payments_count=1,
                    payments_total=Decimal("30.00"),
                ),
            ],
        )
        handler = GetZReportQueryHandler(
            _session_with(_mock_shift_model(status="CLOSED")),
            FakeShiftTotals(_TOTALS),
            InMemoryShiftClosings([closing]),
        )

        result = handler.handle(GetZReportQuery(shift_id=1))

        assert result["shift"]["status"] == "CLOSED"
        assert result["sales_summary"]["total"] == Decimal("100.00")
        assert result["payments_by_method"] == [
            {"payment_method": "CASH", "count": 2, "total": Decimal("100.00")},
            {"payment_method": "CREDIT", "count": 1, "total": Decimal("30.00")},
        ]
        assert result["customer_payments_by_method"] == []
        assert [item["sku"] for item in result["items_sold"]] == ["CLA-01"]
        reconciliation = result["cash_reconciliation"]
        assert (
            reconciliation["expected_balance"],
            reconciliation["closing_balance"],
            reconciliation["discrepancy"],
        ) == (Decimal("600.00"), Decimal("595.00"), Decimal("-5.00"))
        assert result["closing"]["number"] == "Z-001-CAJA-01-000001"
        # CREDIT is not counted
        assert result["closing"]["counts"] == [
            {
                "payment_method": "CASH",
                "expected": Decimal("600.00"),
                "counted": Decimal("595.00"),
                "difference": Decimal("-5.00"),
                "justification": "Faltante",
            }
        ]


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
