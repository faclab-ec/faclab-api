"""Resultados de notas de crédito que publica faclab-invoicing en
`credit_notes.results` (contrato `contracts/events/credit_notes.results/v1`).

La empresa viene en el header `faclab-tenant-id`, o en el sobre, y el consumidor
la fija antes de llamar al handler: un mensaje sin empresa se descarta. Autorizada,
la nota queda con su número y, si la venta quedó acreditada por completo, su factura
en CREDITED; rechazada, queda con el motivo y se puede volver a pedir.
"""

from datetime import datetime
from typing import Any

import structlog

from src.invoicing.app.commands.credit_notes import (
    ApplyCreditNoteResultCommand,
    ApplyCreditNoteResultCommandHandler,
)
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import current_tenant
from src.shared.infra.events.scope import create_sync_scope

logger = structlog.get_logger(__name__)

CREDIT_NOTES_RESULTS_TOPIC = "credit_notes.results"
CREDIT_NOTE_AUTHORIZED = "CreditNoteAuthorized"
CREDIT_NOTE_REJECTED = "CreditNoteRejected"
# Versions of the contract this consumer understands
SUPPORTED_SCHEMA_VERSIONS = (1,)


def _authorized_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def handle_credit_note_message(message: dict[str, Any]) -> None:
    """Los errores que reintentar no arregla se registran y el mensaje se da por
    procesado; cualquier otro (p. ej. la base de datos caída) se propaga para que
    el consumidor lo reintente."""
    event_type = message.get("event_type")
    schema_version = message.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        logger.error(
            "credit_note_message_unsupported_version",
            event_type=event_type,
            schema_version=schema_version,
        )
        return
    if event_type not in (CREDIT_NOTE_AUTHORIZED, CREDIT_NOTE_REJECTED):
        return

    payload = message.get("payload") or {}
    try:
        credit_note_id = int(payload["credit_note_id"])
        document_id = str(payload["document_id"])
        authorized_at = _authorized_at(payload.get("authorized_at"))
    except (KeyError, TypeError, ValueError):
        # Never the whole message: only what identifies it and what is missing
        logger.error(
            "credit_note_message_invalid", event_type=event_type, keys=sorted(payload)
        )
        return

    if current_tenant() is None:
        # Without a tenant it can't be looked up, and a retry won't bring one
        logger.error(
            "credit_note_message_without_tenant",
            credit_note_id=credit_note_id,
            document_id=document_id,
        )
        return

    command = ApplyCreditNoteResultCommand(
        credit_note_id=credit_note_id,
        document_id=document_id,
        authorized=event_type == CREDIT_NOTE_AUTHORIZED,
        number=payload.get("number"),
        access_code=payload.get("access_code"),
        authorized_at=authorized_at,
        reason=payload.get("reason"),
    )
    if not command.authorized:
        logger.warning(
            "credit_note_rejected",
            credit_note_id=credit_note_id,
            document_id=document_id,
        )
    try:
        with create_sync_scope() as scope:
            scope.get(ApplyCreditNoteResultCommandHandler).handle(command)
    except NotFoundError as exc:
        logger.error(
            "credit_note_result_not_applied",
            credit_note_id=credit_note_id,
            document_id=document_id,
            error=exc.message,
        )
