"""Pedir notas de crédito a faclab-invoicing y aplicar su resultado (S4.5).

Una devolución de una venta facturada la pide al completarse; la de una venta aún
sin autorizar, cuando su factura se autoriza. La factura autorizada de una venta
que ya se anuló la pide un usuario, desde su discrepancia (S4.3).

La factura a consumidor final no admite nota de crédito (NAC-DGERCGC25-00000014,
art. 3): el POS bloquea esa devolución antes de llegar aquí.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy.orm import Session
from wireup import injectable

from src.invoicing.app.repositories import (
    CreditNoteRepository,
    InvoiceDiscrepancyRepository,
)
from src.invoicing.domain.entities import (
    CreditNote,
    CreditNoteStatus,
    DiscrepancyKind,
    DiscrepancyStatus,
)
from src.invoicing.domain.events import CreditNoteRequested
from src.invoicing.domain.exceptions import (
    CreditNoteAlreadyRequestedError,
    CreditNoteNotApplicableError,
    FinalConsumerCreditNoteError,
)
from src.pos.refund.app.repositories import RefundItemRepository, RefundRepository
from src.pos.refund.domain.entities import Refund, RefundStatus
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import Sale, SaleStatus
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError

logger = structlog.get_logger(__name__)

# The XML requires a motivo: a refund without a reason (one made before its sale
# was invoiced) says what it is
DEFAULT_REASON = "Devolución"


def _publish_requested(
    publisher: EventPublisher, session: Session, note: CreditNote
) -> None:
    publisher.publish(
        CreditNoteRequested(
            aggregate_id=note.require_id(),
            credit_note_id=note.require_id(),
            sale_id=note.sale_id,
        ),
        # The message goes to the outbox in this transaction
        session=session,
    )


@dataclass
class RequestRefundCreditNotesCommand(Command):
    """Las devoluciones completadas de la venta que aún no tienen su nota"""

    sale_id: int


@injectable(lifetime="scoped")
class RequestRefundCreditNotesCommandHandler(
    CommandHandler[RequestRefundCreditNotesCommand, list[int]]
):
    """Pide una nota por cada devolución completada sin ella, si la venta ya está
    facturada; si no, esperan a que lo esté. Dice cuáles pidió."""

    def __init__(
        self,
        sales: SaleRepository,
        refunds: RefundRepository,
        credit_notes: CreditNoteRepository,
        event_publisher: EventPublisher,
        session: Session,
    ):
        self.sales = sales
        self.refunds = refunds
        self.credit_notes = credit_notes
        self.event_publisher = event_publisher
        self.session = session

    def _handle(self, command: RequestRefundCreditNotesCommand) -> list[int]:
        sale = self.sales.get_by_id(command.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")
        if sale.status != SaleStatus.INVOICED:
            return []

        completed = self.refunds.filter_by(
            original_sale_id=command.sale_id, status=RefundStatus.COMPLETED.value
        )
        requested = {
            note.refund_id
            for note in self.credit_notes.of_refunds(r.require_id() for r in completed)
        }
        pending = [r for r in completed if r.id not in requested]
        if not pending:
            return []
        if not self._admits_credit_notes(sale, pending):
            return []
        return [self._request(sale, refund) for refund in pending]

    def _admits_credit_notes(self, sale: Sale, pending: list[Refund]) -> bool:
        refund_ids = [refund.id for refund in pending]
        if sale.customer_id is None:
            # Only a refund made while its invoice was rejected and sent again
            # gets here, or one the policy allowed (FINAL_CONSUMER_REFUNDS_ALLOWED)
            logger.warning(
                "credit_note_not_possible_final_consumer",
                sale_id=sale.id,
                refund_ids=refund_ids,
            )
            return False
        if sale.invoice_id is None:
            logger.error(
                "credit_note_without_invoice_id", sale_id=sale.id, refund_ids=refund_ids
            )
            return False
        return True

    def _request(self, sale: Sale, refund: Refund) -> int:
        note = self.credit_notes.create(
            CreditNote(
                sale_id=sale.require_id(),
                refund_id=refund.require_id(),
                invoice_id=str(sale.invoice_id),
                reason=refund.reason or DEFAULT_REASON,
                subtotal=refund.subtotal,
                tax=refund.tax,
                total=refund.total,
                requested_at=datetime.now(),
            )
        )
        _publish_requested(self.event_publisher, self.session, note)
        return note.require_id()


@dataclass
class RequestCancelledSaleCreditNoteCommand(Command):
    """La factura autorizada de una venta que ya se anuló, desde su discrepancia"""

    discrepancy_id: int
    reason: str


@injectable(lifetime="scoped")
class RequestCancelledSaleCreditNoteCommandHandler(
    CommandHandler[RequestCancelledSaleCreditNoteCommand, dict]
):
    """Acredita toda la factura: el stock y el dinero ya volvieron al anular la
    venta. Queda en la bitácora."""

    def __init__(
        self,
        discrepancies: InvoiceDiscrepancyRepository,
        sales: SaleRepository,
        credit_notes: CreditNoteRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
        session: Session,
    ):
        self.discrepancies = discrepancies
        self.sales = sales
        self.credit_notes = credit_notes
        self.event_publisher = event_publisher
        self.audit = audit
        self.session = session

    def _handle(self, command: RequestCancelledSaleCreditNoteCommand) -> dict:
        discrepancy = self.discrepancies.get_by_id(command.discrepancy_id)
        if discrepancy is None:
            raise NotFoundError(
                f"Invoice discrepancy {command.discrepancy_id} not found"
            )
        invoice_id = discrepancy.invoice_id
        if (
            discrepancy.kind != DiscrepancyKind.AUTHORIZED_ON_CANCELLED
            or discrepancy.status == DiscrepancyStatus.RESOLVED
            or invoice_id is None
        ):
            raise CreditNoteNotApplicableError(
                discrepancy.require_id(), discrepancy.kind, discrepancy.status
            )
        sale = self.sales.get_by_id(discrepancy.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {discrepancy.sale_id} not found")
        sale_id = sale.require_id()
        if sale.customer_id is None:
            raise FinalConsumerCreditNoteError(sale_id)
        if self.credit_notes.of_cancelled_sale(sale_id) is not None:
            raise CreditNoteAlreadyRequestedError(sale_id)

        note = self.credit_notes.create(
            CreditNote(
                sale_id=sale_id,
                invoice_id=invoice_id,
                reason=command.reason,
                # What the sale charged: its subtotal is before the global discount
                subtotal=sale.subtotal - sale.discount,
                tax=sale.total - sale.subtotal + sale.discount,
                total=sale.total,
                requested_at=datetime.now(),
            )
        )
        self.audit.record(
            AuditAction.CREDIT_NOTE_REQUESTED,
            note.require_id(),
            before=None,
            after={
                "status": note.status,
                "sale_id": sale_id,
                "invoice_id": invoice_id,
                "total": note.total,
                "reason": note.reason,
            },
            branch_id=sale.branch_id,
        )
        _publish_requested(self.event_publisher, self.session, note)
        return note.dict()


@dataclass
class RequestCreditNoteAgainCommand(Command):
    credit_note_id: int


@injectable(lifetime="scoped")
class RequestCreditNoteAgainCommandHandler(
    CommandHandler[RequestCreditNoteAgainCommand, dict]
):
    """Después de un rechazo (emite otra, con otro número) o si su resultado no
    llega (faclab-invoicing no emite otra: vuelve a publicarlo). Queda en la
    bitácora."""

    def __init__(
        self,
        credit_notes: CreditNoteRepository,
        sales: SaleRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
        session: Session,
    ):
        self.credit_notes = credit_notes
        self.sales = sales
        self.event_publisher = event_publisher
        self.audit = audit
        self.session = session

    def _handle(self, command: RequestCreditNoteAgainCommand) -> dict:
        note = self.credit_notes.get_by_id(command.credit_note_id)
        if note is None:
            raise NotFoundError(f"Credit note {command.credit_note_id} not found")
        before = {"status": note.status, "rejection_reason": note.rejection_reason}
        note.request_again()
        note = self.credit_notes.update(note)

        sale = self.sales.get_by_id(note.sale_id)
        self.audit.record(
            AuditAction.CREDIT_NOTE_REQUESTED_AGAIN,
            note.require_id(),
            before=before,
            after={"status": note.status, "sale_id": note.sale_id},
            branch_id=sale.branch_id if sale else None,
        )
        _publish_requested(self.event_publisher, self.session, note)
        return note.dict()


@dataclass
class ApplyCreditNoteResultCommand(Command):
    """Lo que faclab-invoicing publica en `credit_notes.results`"""

    credit_note_id: int
    document_id: str
    authorized: bool
    number: str | None = None
    access_code: str | None = None
    authorized_at: datetime | None = None
    reason: str | None = None


@injectable(lifetime="scoped")
class ApplyCreditNoteResultCommandHandler(
    CommandHandler[ApplyCreditNoteResultCommand, dict]
):
    """Deja la nota autorizada o rechazada. Cuando la venta queda acreditada por
    completo, su factura pasa a CREDITED; la venta sigue como está para que cajas
    y reportes cuenten lo que devolvieron sus devoluciones. Los mensajes de Kafka
    pueden llegar más de una vez: un resultado repetido no hace nada."""

    def __init__(
        self,
        credit_notes: CreditNoteRepository,
        sales: SaleRepository,
        sale_items: SaleItemRepository,
        refunds: RefundRepository,
        refund_items: RefundItemRepository,
        discrepancies: InvoiceDiscrepancyRepository,
    ):
        self.credit_notes = credit_notes
        self.sales = sales
        self.sale_items = sale_items
        self.refunds = refunds
        self.refund_items = refund_items
        self.discrepancies = discrepancies

    def _handle(self, command: ApplyCreditNoteResultCommand) -> dict:
        note = self.credit_notes.get_by_id(command.credit_note_id)
        if note is None:
            raise NotFoundError(f"Credit note {command.credit_note_id} not found")

        if not command.authorized:
            if note.reject(
                command.document_id,
                command.reason,
                command.number,
                command.access_code,
            ):
                note = self.credit_notes.update(note)
            return note.dict()

        if note.authorize(
            command.document_id,
            command.number,
            command.access_code,
            command.authorized_at,
        ):
            note = self.credit_notes.update(note)
            self._credit_sale(note)
        return note.dict()

    def _credit_sale(self, note: CreditNote) -> None:
        sale = self.sales.get_by_id(note.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {note.sale_id} not found")
        if note.refund_id is None:
            # The invoice of a cancelled sale: the whole invoice is credited
            sale.credit_invoice(note.invoice_id)
            self.sales.update(sale)
            for discrepancy in self.discrepancies.unresolved(
                DiscrepancyKind.AUTHORIZED_ON_CANCELLED, note.sale_id
            ):
                discrepancy.resolve()
                self.discrepancies.update(discrepancy)
            return
        if self._fully_credited(sale):
            sale.credit_invoice()
            self.sales.update(sale)

    def _fully_credited(self, sale: Sale) -> bool:
        """Todo lo vendido se devolvió y cada devolución tiene su nota autorizada"""
        sale_id = sale.require_id()
        refunds = self.refunds.filter_by(
            original_sale_id=sale_id, status=RefundStatus.COMPLETED.value
        )
        notes = self.credit_notes.of_refunds(r.require_id() for r in refunds)
        authorized = {
            note.refund_id
            for note in notes
            if note.status == CreditNoteStatus.AUTHORIZED
        }
        if any(refund.id not in authorized for refund in refunds):
            return False

        refunded: dict[int, Decimal] = {}
        for refund in refunds:
            for item in self.refund_items.filter_by(refund_id=refund.require_id()):
                sold_item = item.original_sale_item_id
                refunded[sold_item] = (
                    refunded.get(sold_item, Decimal(0)) + item.quantity
                )
        return all(
            refunded.get(item.require_id(), 0) >= item.quantity
            for item in self.sale_items.filter_by(sale_id=sale_id)
        )
