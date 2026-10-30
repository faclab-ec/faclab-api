from dataclasses import dataclass
from datetime import datetime

import structlog
from wireup import injectable

from src.invoicing.app.repositories import InvoiceDiscrepancyRepository
from src.invoicing.domain.entities import DiscrepancyKind
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import SaleStatus
from src.sales.domain.specifications import SalesAwaitingInvoice
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


@dataclass
class ReconcileInvoicesCommand(Command):
    """Una pasada de la conciliación en la empresa del contexto"""

    # Sales without an invoice result since before this are overdue
    older_than: datetime
    batch_size: int = 500


@injectable(lifetime="scoped")
class ReconcileInvoicesCommandHandler(CommandHandler[ReconcileInvoicesCommand, dict]):
    """Abre `confirmed_without_result` para cada venta atrasada que no la tiene y
    resuelve las de ventas que ya no lo están (se reenviaron, tuvieron resultado
    o se anularon). Una revisada sigue hasta que la condición desaparece, así
    que no se vuelve a abrir. Recorre las ventas por lotes."""

    def __init__(
        self, sales: SaleRepository, discrepancies: InvoiceDiscrepancyRepository
    ):
        self.sales = sales
        self.discrepancies = discrepancies

    def _handle(self, command: ReconcileInvoicesCommand) -> dict:
        kind = DiscrepancyKind.CONFIRMED_WITHOUT_RESULT
        awaiting = SalesAwaitingInvoice(command.older_than)

        known = self.discrepancies.unresolved(kind)
        sales = {
            sale.id: sale
            for sale in self.sales.get_by_ids({item.sale_id for item in known})
        }
        resolved = 0
        for discrepancy in known:
            sale = sales.get(discrepancy.sale_id)
            if sale is None or not awaiting.is_satisfied_by(sale):
                discrepancy.resolve()
                self.discrepancies.update(discrepancy)
                resolved += 1

        tracked = {item.sale_id for item in known}
        opened = 0
        offset = 0
        while True:
            batch = self.sales.filter_by_spec(
                awaiting, order_by="id", limit=command.batch_size, offset=offset
            )
            for sale in batch:
                sale_id = sale.require_id()
                if sale_id in tracked or not self.discrepancies.open(sale_id, kind):
                    continue
                opened += 1
                logger.warning(
                    "invoice_discrepancy_detected",
                    kind=kind.value,
                    sale_id=sale_id,
                    invoice_status=sale.invoice_status,
                    invoice_requested_at=sale.invoice_requested_at,
                )
            if len(batch) < command.batch_size:
                break
            offset += command.batch_size

        return {"opened": opened, "resolved": resolved}


@dataclass
class OpenInvoiceDiscrepancyCommand(Command):
    """faclab-invoicing autorizó la factura de una venta anulada"""

    sale_id: int
    invoice_id: str


@injectable(lifetime="scoped")
class OpenInvoiceDiscrepancyCommandHandler(
    CommandHandler[OpenInvoiceDiscrepancyCommand, bool]
):
    """Abre `authorized_on_cancelled` si la venta está anulada; dice si la
    abrió (un mensaje repetido no abre otra). La anulación fiscal de esa
    factura es una nota de crédito (S4.5)."""

    def __init__(
        self, sales: SaleRepository, discrepancies: InvoiceDiscrepancyRepository
    ):
        self.sales = sales
        self.discrepancies = discrepancies

    def _handle(self, command: OpenInvoiceDiscrepancyCommand) -> bool:
        sale = self.sales.get_by_id(command.sale_id)
        if sale is None:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")
        if sale.status != SaleStatus.CANCELLED:
            return False
        kind = DiscrepancyKind.AUTHORIZED_ON_CANCELLED
        opened = self.discrepancies.open(command.sale_id, kind, command.invoice_id)
        if opened:
            logger.warning(
                "invoice_discrepancy_detected",
                kind=kind.value,
                sale_id=command.sale_id,
                invoice_id=command.invoice_id,
            )
        return opened


@dataclass
class ResolveInvoiceDiscrepancyCommand(Command):
    """La venta ya no espera su resultado: se reenvió o lo recibió"""

    sale_id: int


@injectable(lifetime="scoped")
class ResolveInvoiceDiscrepancyCommandHandler(
    CommandHandler[ResolveInvoiceDiscrepancyCommand, int]
):
    """Resuelve en la misma transacción su `confirmed_without_result`, así sale
    de la lista sin esperar a la tarea; dice cuántas resolvió"""

    def __init__(self, discrepancies: InvoiceDiscrepancyRepository):
        self.discrepancies = discrepancies

    def _handle(self, command: ResolveInvoiceDiscrepancyCommand) -> int:
        pending = self.discrepancies.unresolved(
            DiscrepancyKind.CONFIRMED_WITHOUT_RESULT, command.sale_id
        )
        for discrepancy in pending:
            discrepancy.resolve()
            self.discrepancies.update(discrepancy)
        return len(pending)


@dataclass
class ReviewInvoiceDiscrepancyCommand(Command):
    discrepancy_id: int
    # From the token, never from the request body
    user_id: int | None = None
    user_name: str | None = None
    note: str | None = None


@injectable(lifetime="scoped")
class ReviewInvoiceDiscrepancyCommandHandler(
    CommandHandler[ReviewInvoiceDiscrepancyCommand, dict]
):
    """Un usuario la marca revisada: deja de estar abierta. Queda en la
    bitácora."""

    def __init__(
        self,
        discrepancies: InvoiceDiscrepancyRepository,
        sales: SaleRepository,
        audit: AuditTrail,
    ):
        self.discrepancies = discrepancies
        self.sales = sales
        self.audit = audit

    def _handle(self, command: ReviewInvoiceDiscrepancyCommand) -> dict:
        discrepancy = self.discrepancies.get_by_id(command.discrepancy_id)
        if discrepancy is None:
            raise NotFoundError(
                f"Invoice discrepancy {command.discrepancy_id} not found"
            )
        before = {"status": discrepancy.status}
        discrepancy.review(command.user_id, command.user_name, command.note)
        discrepancy = self.discrepancies.update(discrepancy)

        sale = self.sales.get_by_id(discrepancy.sale_id)
        self.audit.record(
            AuditAction.INVOICE_DISCREPANCY_REVIEWED,
            discrepancy.require_id(),
            before=before,
            after={
                "status": discrepancy.status,
                "kind": discrepancy.kind,
                "sale_id": discrepancy.sale_id,
                "note": discrepancy.review_note,
            },
            branch_id=sale.branch_id if sale else None,
        )
        return discrepancy.dict()
