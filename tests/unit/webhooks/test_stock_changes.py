"""`stock.changed`, grouped by product and branch (S6.4), over SQLite."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.models import WebhookMessageModel, WebhookStockChangeModel
from src.webhooks.infra.stock_changes import flush_tenant, record_stock_change
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session
from tests.webhooks_kit import WEBHOOK_MODELS, Kit

STOCK = WebhookEventType.STOCK_CHANGED
# Branch 12 has two warehouses (locations 1 and 2, and 3); branch 15 one (4)
LOCATIONS = {1: 101, 2: 101, 3: 102, 4: 103}
WAREHOUSES = {101: 12, 102: 12, 103: 15}


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session(
        [*WEBHOOK_MODELS, ProductModel, WarehouseModel, LocationModel, StockModel]
    )
    for warehouse_id, branch_id in WAREHOUSES.items():
        db.add(
            WarehouseModel(
                id=warehouse_id, branch_id=branch_id, name="B", code=f"B{warehouse_id}"
            )
        )
    for location_id, warehouse_id in LOCATIONS.items():
        db.add(
            LocationModel(
                id=location_id,
                warehouse_id=warehouse_id,
                name="U",
                code=f"U{location_id}",
            )
        )
    for product_id, sku in ((7, "MART-1"), (8, "CLAV-2")):
        db.add(ProductModel(id=product_id, name=sku, sku=sku, unit_of_measure_id=1))
    rows = [(7, 1, "10", "2"), (7, 3, "5", "0"), (7, 4, "9", "0"), (8, 1, "3", "0")]
    for product_id, location_id, quantity, reserved in rows:
        db.add(
            StockModel(
                product_id=product_id,
                location_id=location_id,
                quantity=Decimal(quantity),
                reserved_quantity=Decimal(reserved),
            )
        )
    db.flush()
    yield db
    db.close()


@pytest.fixture
def kit(session) -> Kit:
    return Kit(session)


def _record(kit: Kit, *changes: tuple[int, int | None]) -> None:
    for product_id, location_id in changes:
        record_stock_change(kit.session, kit.outbox, product_id, location_id)


def _told(session: Session) -> list[dict]:
    messages = session.scalars(
        select(WebhookMessageModel).order_by(WebhookMessageModel.id)
    )
    return [message.payload for message in messages]


def test_nothing_is_kept_while_nobody_subscribes(kit, session):
    kit.create(event_types=[WebhookEventType.SALE_CONFIRMED])

    _record(kit, (7, 1))

    assert session.scalars(select(WebhookStockChangeModel)).all() == []


def test_a_row_without_location_has_no_branch_to_tell(kit, session):
    kit.create(event_types=[STOCK])

    _record(kit, (7, None))

    assert session.scalars(select(WebhookStockChangeModel)).all() == []


def test_the_changes_are_told_once_per_product_and_branch(kit, session):
    endpoint = kit.create(event_types=[STOCK])
    # A sale of two lines of 7 and one of 8, and a transfer reserving 7
    _record(kit, (7, 1), (7, 1), (8, 1), (7, 2), (7, 4))

    assert {
        row.tenant_id for row in session.scalars(select(WebhookStockChangeModel))
    } == {TEST_TENANT_ID}
    taken = flush_tenant(session, kit.outbox)

    assert taken == 5
    assert [
        (m["data"]["productId"], m["data"]["branchId"]) for m in _told(session)
    ] == [
        (7, 12),
        (7, 15),
        (8, 12),
    ]
    first, other_branch, second = (m["data"] for m in _told(session))
    # Every location of branch 12: (10 - 2) + 5
    assert first == {"productId": 7, "sku": "MART-1", "branchId": 12, "available": "13"}
    assert other_branch["available"] == "9"
    assert second["available"] == "3"
    assert session.scalars(select(WebhookStockChangeModel)).all() == []
    assert kit.history(endpoint["id"])["total"] == 3
    # Nothing left: the next batch tells nothing
    assert flush_tenant(session, kit.outbox) == 0


def test_a_group_of_one_client_carries_it_as_origin(kit, session):
    mine = kit.client(name="Tienda")
    excluding = kit.create(
        client_id=mine.require_id(), event_types=[STOCK], exclude_own_changes=True
    )
    company = kit.create(event_types=[STOCK])
    with tenant_scope(
        TenantContext(TEST_TENANT_ID, TenantSource.REQUEST, integration_id=mine.id)
    ):
        _record(kit, (7, 1), (8, 1))
    # Product 8 also changed by the POS: not only the client's change
    _record(kit, (8, 1))

    flush_tenant(session, kit.outbox)

    told = _told(session)
    assert [(m["data"]["productId"], m["originClientId"]) for m in told] == [
        (7, mine.public_id),
        (8, None),
    ]
    # The client's own change of 7 skipped its endpoint; 8 reached both
    assert kit.history(excluding["id"])["total"] == 1
    assert kit.history(company["id"])["total"] == 2
