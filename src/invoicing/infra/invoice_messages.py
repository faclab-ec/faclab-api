"""Resultados de facturación que publica faclab-invoicing en el topic `invoices`.

faclab-invoicing usa ese topic como su propia máquina de estados (created →
signed → sent → authorized | rejected) y publica ahí cada transición. Core lo lee
con su propio consumer group y solo actúa cuando el SRI autoriza la factura: la
venta pasa a INVOICED. La forma del mensaje es el contrato
`contracts/events/invoices/v1.schema.json`.
"""

from typing import Any

import structlog

from src.sales.app.commands.invoice_sale import (
    InvoiceSaleCommand,
    InvoiceSaleCommandHandler,
)
from src.sales.domain.exceptions import InvalidSaleStatusError
from src.shared.domain.exceptions import NotFoundError
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

    try:
        with create_sync_scope() as scope:
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
