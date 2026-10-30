"""Conciliación periódica entre las ventas y faclab-invoicing (S4.3).

El worker la corre cada INVOICE_RECONCILIATION_INTERVAL_SECONDS. Busca como
faclab_worker las empresas con ventas confirmadas sin resultado de facturación
desde hace INVOICE_RECONCILIATION_PENDING_MINUTES, o con discrepancias de ese
tipo sin resolver, y en cada una corre `ReconcileInvoicesCommand` en su contexto
(bajo RLS). Al final publica cuántas hay abiertas por tipo.

Solo usa el estado que el core ya tiene (`invoice_status`, `invoice_requested_at`):
no consulta a faclab-invoicing. Dos workers a la vez solo repiten trabajo, el
índice único parcial evita discrepancias duplicadas.
"""

from datetime import datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from src.invoicing.app.commands.discrepancies import (
    ReconcileInvoicesCommand,
    ReconcileInvoicesCommandHandler,
)
from src.invoicing.domain.entities import DiscrepancyKind, DiscrepancyStatus
from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.sales.domain.specifications import SalesAwaitingInvoice
from src.sales.infra.models import SaleModel
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.telemetry_instruments import reconciliation_discrepancies

logger = structlog.get_logger(__name__)


def tenants_to_reconcile(
    session_maker: sessionmaker[Session], older_than: datetime
) -> list[UUID]:
    """Empresas con ventas atrasadas o con `confirmed_without_result` sin
    resolver (para cerrarlas), de todas las empresas"""
    awaiting = select(SaleModel.tenant_id).where(
        *SalesAwaitingInvoice(older_than).to_query_criteria()
    )
    unresolved = select(InvoiceDiscrepancyModel.tenant_id).where(
        InvoiceDiscrepancyModel.kind == DiscrepancyKind.CONFIRMED_WITHOUT_RESULT.value,
        InvoiceDiscrepancyModel.status != DiscrepancyStatus.RESOLVED.value,
    )
    with session_maker() as session:
        return sorted(set(session.scalars(awaiting.union(unresolved)).all()))


def open_by_kind(session_maker: sessionmaker[Session]) -> dict[str, int]:
    """Las abiertas de todas las empresas, por tipo (sin el detalle por empresa:
    no va como atributo de métrica)"""
    statement = (
        select(InvoiceDiscrepancyModel.kind, func.count())
        .where(InvoiceDiscrepancyModel.status == DiscrepancyStatus.OPEN.value)
        .group_by(InvoiceDiscrepancyModel.kind)
    )
    with session_maker() as session:
        counts = dict(session.execute(statement).tuples().all())
    return {kind.value: counts.get(kind.value, 0) for kind in DiscrepancyKind}


def reconcile_tenant(tenant_id: UUID, older_than: datetime) -> dict:
    tenant = TenantContext(tenant_id, TenantSource.TASK)
    with create_sync_scope(tenant=tenant) as scope:
        return scope.get(ReconcileInvoicesCommandHandler).handle(
            ReconcileInvoicesCommand(older_than=older_than)
        )


def reconcile() -> dict[str, int]:
    """The worker's task: one pass over every tenant that needs it. A tenant that
    fails is logged and the rest go on; the task fails if any did"""
    from config import config
    from src.shared.infra.database import worker_session_maker

    older_than = datetime.now() - timedelta(
        minutes=config.INVOICE_RECONCILIATION_PENDING_MINUTES
    )
    opened = resolved = failed = 0
    for tenant_id in tenants_to_reconcile(worker_session_maker(), older_than):
        try:
            result = reconcile_tenant(tenant_id, older_than)
        except Exception:
            failed += 1
            logger.exception("invoice_reconciliation_failed", tenant_id=str(tenant_id))
            continue
        opened += result["opened"]
        resolved += result["resolved"]

    open_now = open_by_kind(worker_session_maker())
    for kind, count in open_now.items():
        reconciliation_discrepancies.set(count, {"kind": kind})
    logger.info(
        "invoice_reconciliation_done",
        opened=opened,
        resolved=resolved,
        failed_tenants=failed,
        open=open_now,
    )
    if failed:
        raise RuntimeError(f"Invoice reconciliation failed in {failed} tenant(s)")
    return {"opened": opened, "resolved": resolved}
