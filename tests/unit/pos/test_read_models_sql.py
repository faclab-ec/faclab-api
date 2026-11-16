"""The POS read models query the models directly, so they filter by tenant
themselves: run them against SQLite with a second tenant that reuses ids,
SKUs and dates."""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from src.catalog.product.infra.models import (
    CategoryModel,
    ProductModel,
    ProductPresentationModel,
)
from src.catalog.uom.infra.models import UnitOfMeasureModel
from src.customers.infra.models import CustomerModel
from src.pos.cash.infra.models import CashMovementModel
from src.pos.refund.infra.models import RefundItemModel, RefundModel, RefundPaymentModel
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
from src.pos.sales.app.queries.generate_receipt import (
    GenerateReceiptQuery,
    GenerateReceiptQueryHandler,
)
from src.pos.shift.domain.closing import ShiftClosingLine
from src.pos.shift.infra.models import (
    ShiftClosingLineModel,
    ShiftClosingModel,
    ShiftModel,
)
from src.pos.shift.infra.repositories import SqlAlchemyShiftClosingRepository
from src.pos.shift.infra.totals import SqlAlchemyShiftTotalsReader
from src.receivables.infra.models import CustomerPaymentModel
from src.sales.domain.entities import PaymentMethod
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.tenancy.infra.models import TenantModel
from tests.sqlite import sqlite_session
from tests.unit.pos.closings import make_closing

OTHER = TenantContext(UUID("00000000-0000-4000-8000-0000000000b2"), TenantSource.TASK)
DAY = date(2026, 3, 14)

_MODELS = (
    CategoryModel,
    UnitOfMeasureModel,
    ProductModel,
    ProductPresentationModel,
    CustomerModel,
    ShiftModel,
    SaleModel,
    SaleItemModel,
    PaymentModel,
    RefundModel,
    RefundItemModel,
    RefundPaymentModel,
    CashMovementModel,
    CustomerPaymentModel,
    ShiftClosingModel,
    ShiftClosingLineModel,
)


def _sell(session: Session, shift_id: int, sale_id: int, amount: str) -> None:
    """A confirmed cash sale of one unit of product `sale_id`"""
    total = Decimal(amount)
    session.add(
        ProductModel(id=sale_id, name="Martillo", sku="MAR-01", unit_of_measure_id=1)
    )
    session.add(CustomerModel(id=sale_id, name="Cliente", tax_id="0912345678"))
    session.add(ShiftModel(id=shift_id, cashier_name=f"Caja {shift_id}"))
    session.flush()
    session.add(
        SaleModel(
            id=sale_id,
            customer_id=sale_id,
            shift_id=shift_id,
            status="CONFIRMED",
            sale_date=datetime(2026, 3, 14, 10),
            subtotal=total,
            total=total,
        )
    )
    session.flush()
    session.add(
        SaleItemModel(sale_id=sale_id, product_id=sale_id, quantity=1, unit_price=total)
    )
    session.add(PaymentModel(sale_id=sale_id, amount=total, payment_method="CASH"))
    session.add(CashMovementModel(shift_id=shift_id, type="IN", amount=Decimal("5")))
    session.commit()


@pytest.fixture
def session() -> Iterator[Session]:
    db = sqlite_session(_MODELS)
    db.add(TenantModel(id=OTHER.tenant_id, ruc="0999999999001", legal_name="B"))
    db.commit()
    _sell(db, shift_id=1, sale_id=1, amount="100")
    with use_tenant(OTHER):
        _sell(db, shift_id=2, sale_id=2, amount="900")
    yield db
    db.close()


def _x(session: Session) -> GetXReportQueryHandler:
    return GetXReportQueryHandler(session, SqlAlchemyShiftTotalsReader(session))


def test_the_x_report_only_sees_the_tenants_sales(session):
    report = _x(session).handle(GetXReportQuery(shift_id=1))

    assert report["sales_summary"]["total"] == Decimal("100")
    assert [row["total"] for row in report["payments_by_method"]] == [Decimal("100")]
    assert [row["quantity"] for row in report["items_sold"]] == [1]


def test_another_tenants_shift_is_not_found(session):
    z_handler = GetZReportQueryHandler(
        session,
        SqlAlchemyShiftTotalsReader(session),
        SqlAlchemyShiftClosingRepository(session),
    )

    with pytest.raises(NotFoundError):
        _x(session).handle(GetXReportQuery(shift_id=2))
    with pytest.raises(NotFoundError):
        z_handler.handle(GetZReportQuery(shift_id=2))


def test_the_totals_of_another_tenants_shift_are_empty(session):
    totals = SqlAlchemyShiftTotalsReader(session)

    assert totals.of_shift(1).cash_summary() == {
        "cash_sales": Decimal("100"),
        "cash_refunds": 0,
        "customer_payments": 0,
        "cash_in": Decimal("5"),
        "cash_out": 0,
    }
    assert totals.of_shift(2).cash_summary() == {
        "cash_sales": 0,
        "cash_refunds": 0,
        "customer_payments": 0,
        "cash_in": 0,
        "cash_out": 0,
    }
    assert totals.of_shift(2).items_sold == []


def test_a_closing_is_kept_and_read_back_only_in_its_tenant(session):
    """S5.9: the Z closing and its lines round-trip; another tenant's closing
    and numbers are not seen, and each terminal has its own correlative"""
    closings = SqlAlchemyShiftClosingRepository(session)
    totals = SqlAlchemyShiftTotalsReader(session).of_shift(1)
    with use_tenant(OTHER):
        SqlAlchemyShiftClosingRepository(session).add(
            make_closing(shift_id=2, sequence=1, number="Z-B-000001")
        )

    saved = closings.add(
        make_closing(
            shift_id=1,
            terminal_id=None,
            branch_id=None,
            sequence=closings.next_sequence(None),
            number="Z-000001",
            items_sold=totals.items_sold,
            lines=[
                ShiftClosingLine(
                    payment_method=PaymentMethod.CASH,
                    payments_count=1,
                    payments_total=Decimal("100"),
                    expected=Decimal("105"),
                    counted=Decimal("100"),
                    difference=Decimal("-5"),
                    justification="Faltante",
                ),
                ShiftClosingLine(payment_method=PaymentMethod.CREDIT),
            ],
        )
    )
    session.commit()

    read = closings.of_shift(1)
    assert read is not None and read.id == saved.id
    assert read.number == "Z-000001"
    assert [(i.sku, i.quantity, i.total) for i in read.items_sold] == [
        ("MAR-01", Decimal("1"), Decimal("100"))
    ]
    assert [
        (str(line.payment_method), line.counted, line.justification)
        for line in read.lines
    ] == [("CASH", Decimal("100"), "Faltante"), ("CREDIT", None, None)]
    assert closings.of_shift(2) is None
    assert closings.numbers_of([1, 2]) == {1: "Z-000001"}
    assert closings.next_sequence(None) == 2
    assert closings.next_sequence(3) == 1


def test_daily_reports_only_add_up_the_tenants_sales(session):
    daily = GetDailySummaryQueryHandler(session).handle(GetDailySummaryQuery(date=DAY))
    by_method = GetSalesByPaymentMethodQueryHandler(session).handle(
        GetSalesByPaymentMethodQuery(from_date=DAY, to_date=DAY)
    )

    assert daily["total_sales"] == 1
    assert daily["total_amount"] == Decimal("100")
    assert [row["total_amount"] for row in by_method] == [Decimal("100")]


def test_another_tenants_receipt_is_not_found(session):
    handler = GenerateReceiptQueryHandler(session)

    assert handler.handle(GenerateReceiptQuery(sale_id=1))["total"] == Decimal("100")
    with pytest.raises(NotFoundError):
        handler.handle(GenerateReceiptQuery(sale_id=2))
