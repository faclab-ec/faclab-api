"""`stock.changed`, grouped (S6.4, ADR-0009).

Every write of a stock row (a movement, the POS taking or putting back, a
transfer reserving or releasing) publishes `StockCreated` or `StockUpdated` in
its transaction; while some endpoint of the tenant subscribes to
`stock.changed`, the handler inserts a row in `webhook_stock_changes` (only
inserts: concurrent sales don't wait for each other there). Every
WEBHOOK_STOCK_BATCH_SECONDS the worker takes the rows of each tenant, groups
them by product and branch and enqueues one `stock.changed` per group with the
branch's available quantity at that moment, so a sale of 50 lines and a busy
POS tell each product once per batch.
"""

import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from src.catalog.product.infra.models import ProductModel
from src.inventory.location.infra.models import LocationModel
from src.inventory.stock.infra.models import StockModel
from src.inventory.warehouse.infra.models import WarehouseModel
from src.shared.domain.tenant import TenantContext, TenantSource, current_tenant
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.tenant import tenant_criteria
from src.webhooks.app.outbox import WebhookOutbox
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.models import WebhookStockChangeModel
from src.webhooks.infra.schemas import StockChangedData, data_of

logger = structlog.get_logger(__name__)

# The rows of a tenant one transaction groups
BATCH_SIZE = 1000


def record_stock_change(
    session: Session, outbox: WebhookOutbox, product_id: int, location_id: int | None
) -> None:
    """A stock row changed, in the transaction that changed it"""
    if location_id is None or not outbox.subscribed(WebhookEventType.STOCK_CHANGED):
        return
    context = current_tenant()
    if context is None:
        return
    session.execute(
        insert(WebhookStockChangeModel).values(
            tenant_id=context.tenant_id,
            product_id=product_id,
            location_id=location_id,
            origin_integration_id=context.integration_id,
            changed_at=datetime.now(),
        )
    )


def _branches(session: Session, location_ids: Iterable[int]) -> dict[int, int]:
    """location -> its warehouse's branch"""
    rows = session.execute(
        select(LocationModel.id, WarehouseModel.branch_id)
        .join(
            WarehouseModel,
            (WarehouseModel.id == LocationModel.warehouse_id)
            & (WarehouseModel.tenant_id == LocationModel.tenant_id),
        )
        .where(
            LocationModel.id.in_(set(location_ids)),
            *tenant_criteria(LocationModel, WarehouseModel),
        )
    )
    return dict(rows.tuples().all())


def _available(
    session: Session, branch_id: int, product_ids: set[int]
) -> dict[int, Decimal]:
    """What each product has available in every location of the branch"""
    rows = session.execute(
        select(
            StockModel.product_id,
            func.sum(StockModel.quantity - StockModel.reserved_quantity),
        )
        .join(
            LocationModel,
            (LocationModel.id == StockModel.location_id)
            & (LocationModel.tenant_id == StockModel.tenant_id),
        )
        .join(
            WarehouseModel,
            (WarehouseModel.id == LocationModel.warehouse_id)
            & (WarehouseModel.tenant_id == LocationModel.tenant_id),
        )
        .where(
            WarehouseModel.branch_id == branch_id,
            StockModel.product_id.in_(product_ids),
            *tenant_criteria(StockModel, LocationModel, WarehouseModel),
        )
        .group_by(StockModel.product_id)
    )
    return {product_id: Decimal(total or 0) for product_id, total in rows}


def _skus(session: Session, product_ids: set[int]) -> dict[int, str]:
    rows = session.execute(
        select(ProductModel.id, ProductModel.sku).where(
            ProductModel.id.in_(product_ids), *tenant_criteria(ProductModel)
        )
    )
    return dict(rows.tuples().all())


def flush_tenant(session: Session, outbox: WebhookOutbox) -> int:
    """Takes a batch of the context tenant's changes, enqueues a
    `stock.changed` per product and branch and deletes them; how many it took.
    Another worker's batch is skipped (SKIP LOCKED)"""
    changes = session.scalars(
        select(WebhookStockChangeModel)
        .where(*tenant_criteria(WebhookStockChangeModel))
        .order_by(WebhookStockChangeModel.id)
        .with_for_update(skip_locked=True)
        .limit(BATCH_SIZE)
    ).all()
    if not changes:
        return 0
    branches = _branches(session, {change.location_id for change in changes})
    groups: dict[tuple[int, int], list[WebhookStockChangeModel]] = defaultdict(list)
    for change in changes:
        branch_id = branches.get(change.location_id)
        if branch_id is not None:
            groups[(change.product_id, branch_id)].append(change)
    skus = _skus(session, {product_id for product_id, _ in groups})
    by_branch: dict[int, set[int]] = defaultdict(set)
    for product_id, branch_id in groups:
        by_branch[branch_id].add(product_id)
    available = {
        branch_id: _available(session, branch_id, product_ids)
        for branch_id, product_ids in by_branch.items()
    }
    for (product_id, branch_id), grouped in sorted(groups.items()):
        if product_id not in skus:
            continue
        origins = {change.origin_integration_id for change in grouped}
        outbox.enqueue(
            WebhookEventType.STOCK_CHANGED,
            data_of(
                StockChangedData(
                    product_id=product_id,
                    sku=skus[product_id],
                    branch_id=branch_id,
                    available=available[branch_id].get(product_id, Decimal(0)),
                )
            ),
            branch_id=branch_id,
            occurred_at=max(change.changed_at for change in grouped),
            # One client's changes only: the endpoint that excludes them skips it
            origin=origins.pop() if len(origins) == 1 else None,
        )
    session.execute(
        delete(WebhookStockChangeModel).where(
            WebhookStockChangeModel.id.in_([change.id for change in changes]),
            *tenant_criteria(WebhookStockChangeModel),
        )
    )
    return len(changes)


def tenants_with_changes(session_maker: sessionmaker[Session]) -> list[UUID]:
    with session_maker() as session:
        return list(
            session.scalars(select(WebhookStockChangeModel.tenant_id).distinct())
        )


def flush_stock_changes(
    session_maker: sessionmaker[Session] | None = None,
    budget_seconds: float = 20.0,
) -> int:
    """The worker's task: every tenant's batches, for up to `budget_seconds`
    (its health needs it back within a minute). A tenant that fails is logged
    and the rest go on; the task fails if any did"""
    if session_maker is None:
        from src.shared.infra.database import worker_session_maker

        session_maker = worker_session_maker()
    deadline = time.monotonic() + budget_seconds
    taken = failed = 0
    for tenant_id in tenants_with_changes(session_maker):
        tenant = TenantContext(tenant_id, TenantSource.TASK)
        while time.monotonic() < deadline:
            try:
                with create_sync_scope(tenant=tenant) as scope:
                    batch = flush_tenant(scope.get(Session), scope.get(WebhookOutbox))
            except Exception:
                failed += 1
                logger.exception(
                    "webhook_stock_changes_failed", tenant_id=str(tenant_id)
                )
                break
            taken += batch
            if batch < BATCH_SIZE:
                break
    if taken:
        logger.info("webhook_stock_changes_flushed", changes=taken)
    if failed:
        raise RuntimeError(f"stock.changed failed in {failed} tenant(s)")
    return taken
