from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from wireup import injectable

from src.organization.app.repositories import BranchRepository, PosTerminalRepository
from src.pos.shift.app.repositories import ShiftClosingRepository, ShiftRepository
from src.pos.shift.app.totals import ShiftTotalsReader
from src.pos.shift.domain.closing import (
    MethodCount,
    ShiftClosing,
    closing_number,
    count_lines,
)
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.events import ShiftClosed
from src.pos.shift.domain.exceptions import ShiftAlreadyClosedError
from src.sales.domain.entities import PaymentMethod
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CloseShiftCommand(Command):
    """Comando para cerrar un turno con su arqueo (S5.9): lo contado de cada
    medio de pago y la justificación de cada diferencia que supere el umbral"""

    shift_id: int
    # [{"payment_method", "counted", "justification"}]
    counts: list[dict] = field(default_factory=list)
    # The cash counted, from a request without the CASH count (before S5.9)
    closing_balance: Decimal | None = None
    justification_threshold: Decimal = Decimal("0")
    notes: str | None = None
    closed_by: str | None = None
    closed_by_user_id: int | None = None


@injectable(lifetime="scoped")
class CloseShiftCommandHandler(CommandHandler[CloseShiftCommand, dict]):
    """Cierra un turno y escribe su cierre Z en la misma transacción. El turno
    queda bloqueado mientras tanto: los documentos que escriben en él esperan y,
    al seguir, lo encuentran cerrado (`NO_OPEN_SHIFT`)."""

    def __init__(
        self,
        repo: ShiftRepository,
        closings: ShiftClosingRepository,
        totals: ShiftTotalsReader,
        terminals: PosTerminalRepository,
        branches: BranchRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.closings = closings
        self.totals = totals
        self.terminals = terminals
        self.branches = branches
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: CloseShiftCommand) -> dict:
        # Locked before reading what it moved: no document gets in afterwards
        shift = self.repo.first_for_update(id=command.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {command.shift_id} not found")
        if shift.status != ShiftStatus.OPEN:
            raise ShiftAlreadyClosedError(shift.require_id())

        totals = self.totals.of_shift(shift.require_id())
        lines = count_lines(
            totals.lines(shift.opening_balance),
            self._counts(command),
            command.justification_threshold,
        )
        cash = next(line for line in lines if line.payment_method == PaymentMethod.CASH)

        before_status = shift.status
        shift.close(
            closing_balance=cash.counted or Decimal("0"),
            expected_balance=cash.expected or Decimal("0"),
            closed_by=command.closed_by,
        )
        if command.notes is not None:
            shift.notes = command.notes
        self.repo.update(shift)

        sequence = self.closings.next_sequence(shift.terminal_id)
        closing = self.closings.add(
            ShiftClosing(
                shift_id=shift.require_id(),
                sequence=sequence,
                number=self._number(shift, sequence),
                cashier_name=shift.cashier_name,
                closed_at=shift.closed_at or datetime.now(),
                terminal_id=shift.terminal_id,
                branch_id=shift.branch_id,
                opened_at=shift.opened_at,
                closed_by=command.closed_by,
                closed_by_user_id=command.closed_by_user_id,
                opening_balance=shift.opening_balance,
                sales_count=totals.sales_count,
                sales_subtotal=totals.sales_subtotal,
                sales_tax=totals.sales_tax,
                sales_discount=totals.sales_discount,
                sales_total=totals.sales_total,
                refunds_count=totals.refunds_count,
                refunds_total=totals.refunds_total,
                cash_sales=totals.cash_sales,
                cash_refunds=totals.cash_refunds,
                customer_payments=totals.cash_customer_payments,
                cash_in=totals.cash_in,
                cash_out=totals.cash_out,
                justification_threshold=command.justification_threshold,
                notes=shift.notes,
                items_sold=totals.items_sold,
                lines=lines,
            )
        )

        self.audit.record(
            AuditAction.SHIFT_CLOSED,
            shift.require_id(),
            before={"status": before_status},
            after={
                "status": shift.status,
                "closing_number": closing.number,
                "closing_balance": shift.closing_balance,
                "expected_balance": shift.expected_balance,
                "discrepancy": shift.discrepancy,
                "justification_threshold": command.justification_threshold,
                "counts": [
                    {
                        "payment_method": line.payment_method,
                        "expected": line.expected,
                        "counted": line.counted,
                        "difference": line.difference,
                        "justification": line.justification,
                    }
                    for line in closing.lines
                    if line.countable
                ],
            },
            branch_id=shift.branch_id,
        )

        self.event_publisher.publish(
            ShiftClosed(
                aggregate_id=shift.require_id(),
                shift_id=shift.require_id(),
                cashier_name=shift.cashier_name,
                closing_balance=shift.closing_balance or Decimal("0"),
                expected_balance=shift.expected_balance or Decimal("0"),
                discrepancy=shift.discrepancy or Decimal("0"),
                closing_number=closing.number,
            )
        )

        return {**shift.dict(), "closing_number": closing.number}

    @staticmethod
    def _counts(command: CloseShiftCommand) -> list[MethodCount]:
        counts = [
            MethodCount(
                payment_method=str(count["payment_method"]),
                counted=Decimal(str(count["counted"])),
                justification=count.get("justification"),
            )
            for count in command.counts
        ]
        # A client from before S5.9 sends the cash counted as closing_balance
        has_cash = any(c.payment_method == PaymentMethod.CASH for c in counts)
        if not has_cash and command.closing_balance is not None:
            counts.append(MethodCount(PaymentMethod.CASH, command.closing_balance))
        return counts

    def _number(self, shift: Shift, sequence: int) -> str:
        """`Z-<establishment>-<terminal>-<correlative>`, with the codes they
        have when it closes"""
        terminal = (
            self.terminals.get_by_id(shift.terminal_id)
            if shift.terminal_id is not None
            else None
        )
        branch = (
            self.branches.get_by_id(shift.branch_id)
            if shift.branch_id is not None
            else None
        )
        return closing_number(
            branch.establishment_code if branch else None,
            terminal.code if terminal else None,
            sequence,
        )
