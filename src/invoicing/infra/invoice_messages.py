"""Resultados de facturación que publica faclab-invoicing en el topic `invoices`.

faclab-invoicing usa ese topic como su propia máquina de estados (created →
signed → sent → authorized | rejected) y publica ahí cada transición. Core lo lee
con su propio consumer group y solo actúa cuando el SRI autoriza la factura: la
venta pasa a INVOICED. La forma del mensaje es el contrato
`contracts/events/invoices/v1.schema.json`.

La venta se busca en la empresa del mensaje (header `faclab-tenant-id`), que el
consumidor fija antes de llamar al handler. faclab-invoicing todavía no la envía:
mientras tanto, un mensaje sin empresa corre en la de su venta (ver
`_tenant_of_sale`).
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.sales.app.commands.invoice_sale import (
    InvoiceSaleCommand,
    InvoiceSaleCommandHandler,
)
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.sales.infra.models import SaleModel
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantContext, TenantSource, current_tenant
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)

INVOICES_TOPIC = "invoices"
INVOICE_AUTHORIZED = "InvoiceAuthorized"
INVOICE_REJECTED = "InvoiceRejected"
# Versiones del contrato que este consumidor entiende; sin el campo es v1
SUPPORTED_SCHEMA_VERSIONS = (1,)


def handle_invoice_message(message: dict[str, Any]) -> None:
    """Marca la venta como facturada cuando su factura queda autorizada.

    Los errores que reintentar no arregla se registran y el mensaje se da por
    procesado; cualquier otro (p. ej. la base de datos caída) se propaga para
    que el consumidor lo reintente.
    """
    event_type = message.get("type")
    schema_version = message.get("schema_version", 1)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        # faclab-invoicing publica una versión nueva solo cuando core ya la
        # acepta (contracts/README.md); reintentar no la vuelve legible
        logger.error(
            "invoice_message_unsupported_version",
            event_type=event_type,
            schema_version=schema_version,
        )
        return
    if event_type == INVOICE_REJECTED:
        logger.warning(
            "invoice_rejected",
            sale_id=message.get("saleId"),
            invoice_id=message.get("invoiceId"),
        )
        return
    if event_type != INVOICE_AUTHORIZED:
        return

    try:
        sale_id = int(message["saleId"])
        invoice_id = str(message["invoiceId"])
    except (KeyError, TypeError, ValueError):
        # Never the whole message: only what identifies it and what is missing
        logger.error(
            "invoice_message_invalid", event_type=event_type, keys=sorted(message)
        )
        return

    tenant = None
    if current_tenant() is None:
        tenant_id = _tenant_of_sale(sale_id)
        if tenant_id is None:
            logger.error(
                "invoice_not_applied",
                sale_id=sale_id,
                invoice_id=invoice_id,
                error="sale not found",
            )
            return
        tenant = TenantContext(tenant_id, TenantSource.MESSAGE)

    try:
        with create_sync_scope(tenant=tenant) as scope:
            scope.get(InvoiceSaleCommandHandler).handle(
                InvoiceSaleCommand(sale_id=sale_id, invoice_id=invoice_id)
            )
    except (NotFoundError, InvalidSaleStatusError) as exc:
        # P. ej. la venta se anuló antes de que el SRI autorizara su factura:
        # eso se resuelve con una nota de crédito, no reintentando
        logger.error(
            "invoice_not_applied",
            sale_id=sale_id,
            invoice_id=invoice_id,
            error=exc.message,
        )


def _tenant_of_sale(sale_id: int) -> UUID | None:
    """La empresa de una venta, para un mensaje que no trae la suya.

    Temporal hasta S2.8, cuando faclab-invoicing copie a sus mensajes el header
    `faclab-tenant-id` del `sales.confirmed` que factura. Los ids de venta son
    globales, así que no hay ambigüedad. Es una lectura de plataforma, fuera de
    cualquier empresa: con RLS (S2.4) necesitará el rol `faclab_worker`.
    """
    with create_sync_scope() as scope:
        session = scope.get(Session)
        return session.scalar(
            select(SaleModel.tenant_id).where(SaleModel.id == sale_id)
        )
