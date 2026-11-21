"""The S7.1 metrics through the real app on PostgreSQL: a sale, a sale without
stock, a cancellation and a refund at the POS count what committed; the queue
gauges count, as faclab_worker, every tenant's outbox."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.auth.domain.entities import Role
from src.background import queue_metrics
from src.shared.infra.outbox.models import OutboxMessageModel, OutboxStatus
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

SOURCE = "faclab.sale.source"
MOVEMENTS = "faclab.inventory.movements"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def api(client, auth_headers, terminal) -> Api:
    return Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))


@pytest.fixture
def product(admin_api, shelf) -> dict:
    """10.00 + VAT 15%, 3 units on the terminal's shelf"""
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 3, shelf["id"])
    return product


@pytest.fixture
def shift(api) -> dict:
    return api.post("/api/pos/shifts/open", {"openingBalance": "0"})


def _sale(quantity: int, product_id: int, amount: str) -> dict:
    return {
        "items": [{"productId": product_id, "quantity": quantity}],
        "payments": [{"amount": amount, "paymentMethod": "CASH"}],
    }


@pytest.mark.usefixtures("shift")
def test_a_sale_counts_once_it_committed(api, product, recorded_metrics):
    sale = api.post("/api/pos/sales/quick", _sale(2, product["id"], "23.00"))
    assert sale["status"] == "CONFIRMED"

    collected = recorded_metrics.collect()
    assert collected.points("faclab.sales.confirmed") == [(1, {SOURCE: "pos"})]
    assert (
        collected.total(
            MOVEMENTS, faclab__movement__type="out", faclab__movement__source="sale"
        )
        == 1
    )
    assert collected.points("faclab.sales.failed") == []
    # The request's pool reports its connections under a fixed name
    pools = {
        attrs["db.client.connection.pool.name"]
        for attrs in collected.attributes("db.client.connection.count")
    }
    assert "request" in pools


@pytest.mark.usefixtures("shift")
def test_a_sale_without_stock_is_a_failure_and_a_rejection(
    api, product, recorded_metrics
):
    error = api.error(
        "POST", "/api/pos/sales/quick", 400, json=_sale(5, product["id"], "57.50")
    )
    assert error["code"] == "INSUFFICIENT_STOCK"

    collected = recorded_metrics.collect()
    assert collected.points("faclab.sales.failed") == [
        (1, {"error.code": "INSUFFICIENT_STOCK", SOURCE: "pos"})
    ]
    assert collected.points("faclab.inventory.stock_rejections") == [
        (1, {"faclab.movement.source": "sale"})
    ]
    # Nothing it did before failing committed
    assert collected.total("faclab.sales.confirmed") == 0
    assert collected.total(MOVEMENTS) == 0


@pytest.mark.usefixtures("shift")
def test_a_cancellation_and_a_refund_count(
    api, client, auth_headers, terminal, product, recorded_metrics
):
    manager = Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))
    voided = api.post("/api/pos/sales/quick", _sale(1, product["id"], "11.50"))
    refunded = api.post("/api/pos/sales/quick", _sale(1, product["id"], "11.50"))
    recorded_metrics.collect()

    api.post(f"/api/pos/sales/{voided['id']}/cancel")
    [item] = api.get(f"/api/pos/sales/{refunded['id']}/items")
    refund = api.post(
        "/api/pos/refunds",
        {
            "originalSaleId": refunded["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    manager.post(
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )

    collected = recorded_metrics.collect()
    assert collected.points("faclab.sales.cancelled") == [(1, {SOURCE: "pos"})]
    assert collected.points("faclab.refunds.completed") == [(1, {SOURCE: "pos"})]
    assert (
        collected.total(
            MOVEMENTS, faclab__movement__type="in", faclab__movement__source="sale"
        )
        == 1
    )
    assert (
        collected.total(
            MOVEMENTS, faclab__movement__type="in", faclab__movement__source="refund"
        )
        == 1
    )


def test_the_queue_gauges_count_every_tenant(pg_engine, tenant):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    now = datetime.now()
    with Session(bind=pg_engine) as session:
        for number, (tenant_id, status, age) in enumerate(
            [
                (tenant, OutboxStatus.PENDING, 30),
                (other, OutboxStatus.PENDING, 300),
                (other, OutboxStatus.FAILED, 9000),
                (tenant, OutboxStatus.PUBLISHED, 60),
            ]
        ):
            session.add(
                OutboxMessageModel(
                    event_id=f"e-{number}",
                    event_type="SaleConfirmed",
                    topic="sales.confirmed",
                    payload={},
                    tenant_id=tenant_id,
                    headers={},
                    status=status.value,
                    created_at=now - timedelta(seconds=age),
                )
            )
        session.commit()

    sample = queue_metrics.sample()

    assert sample["outbox_pending"]["sales.confirmed"] == 2
    assert sample["outbox_failed"]["sales.confirmed"] == 1
    assert sample["outbox_oldest_age"]["sales.confirmed"] >= 300
    assert sample["outbox_pending"]["credit_notes.requested"] == 0
    assert sample["dead_letters_pending"] == {"credit_notes.results": 0, "invoices": 0}
