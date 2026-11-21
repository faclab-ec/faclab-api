"""Sales metrics (S7.1): what was confirmed, voided or refunded counts once its
transaction commits; what could not be confirmed, by its error code."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from src.pos.infra.event_handlers import (
    count_refund_completed,
    count_sale_cancelled,
    count_sale_confirmed,
)
from src.pos.infra.metrics import sale_attempt
from src.pos.refund.domain.events import RefundCompleted
from src.sales.domain.events import SaleCancelled, SaleConfirmed
from src.sales.domain.exceptions import InsufficientStockError
from src.shared.domain.exceptions import ValidationError
from src.shared.infra.database import create_session_maker

SOURCE = "faclab.sale.source"


def _session():
    session = create_session_maker("sqlite://")()
    session.execute(text("SELECT 1"))
    return session


def test_a_confirmed_sale_counts_after_the_commit(recorded_metrics):
    session = _session()

    count_sale_confirmed(
        SaleConfirmed(aggregate_id=1, sale_id=1, source="pos"), session=session
    )
    count_sale_confirmed(
        SaleConfirmed(aggregate_id=2, sale_id=2, source="api"), session=session
    )
    assert recorded_metrics.collect().total("faclab.sales.confirmed") == 0
    session.commit()

    points = recorded_metrics.collect().points("faclab.sales.confirmed")
    assert sorted(points, key=str) == [(1, {SOURCE: "api"}), (1, {SOURCE: "pos"})]


def test_a_sale_whose_request_failed_after_its_event_is_not_counted(
    recorded_metrics,
):
    session = _session()

    count_sale_confirmed(
        SaleConfirmed(aggregate_id=1, sale_id=1, source="pos"), session=session
    )
    session.rollback()

    assert recorded_metrics.collect().total("faclab.sales.confirmed") == 0


def test_only_a_confirmed_sale_voided_is_a_cancellation(recorded_metrics):
    session = _session()

    count_sale_cancelled(
        SaleCancelled(aggregate_id=1, sale_id=1, was_confirmed=True, source="api"),
        session=session,
    )
    count_sale_cancelled(
        SaleCancelled(aggregate_id=2, sale_id=2, was_confirmed=False, source="pos"),
        session=session,
    )
    session.commit()

    assert recorded_metrics.collect().points("faclab.sales.cancelled") == [
        (1, {SOURCE: "api"})
    ]


def test_a_completed_refund_counts(recorded_metrics):
    session = _session()

    count_refund_completed(
        RefundCompleted(
            aggregate_id=1, refund_id=1, original_sale_id=1, total=Decimal("5")
        ),
        session=session,
    )
    session.commit()

    assert recorded_metrics.collect().points("faclab.refunds.completed") == [
        (1, {SOURCE: "pos"})
    ]


def test_a_rejected_sale_counts_its_error_code(recorded_metrics):
    with pytest.raises(ValidationError), sale_attempt("api"):
        raise ValidationError("bad payment")

    assert recorded_metrics.collect().points("faclab.sales.failed") == [
        (1, {"error.code": "VALIDATION_ERROR", SOURCE: "api"})
    ]


def test_a_sale_without_stock_is_also_a_stock_rejection(recorded_metrics):
    with pytest.raises(InsufficientStockError), sale_attempt("pos"):
        raise InsufficientStockError(7, Decimal(3), Decimal(1))

    collected = recorded_metrics.collect()
    assert collected.points("faclab.sales.failed") == [
        (1, {"error.code": "INSUFFICIENT_STOCK", SOURCE: "pos"})
    ]
    assert collected.points("faclab.inventory.stock_rejections") == [
        (1, {"faclab.movement.source": "sale"})
    ]


def test_an_unexpected_error_counts_as_internal(recorded_metrics):
    with pytest.raises(RuntimeError), sale_attempt("pos"):
        raise RuntimeError("database is down")

    assert recorded_metrics.collect().points("faclab.sales.failed") == [
        (1, {"error.code": "INTERNAL_ERROR", SOURCE: "pos"})
    ]


def test_a_confirmed_sale_is_no_failure(recorded_metrics):
    with sale_attempt("pos"):
        pass

    assert recorded_metrics.collect().points("faclab.sales.failed") == []
