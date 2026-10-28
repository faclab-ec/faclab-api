from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.pos.cash.app.repositories import CashMovementRepository
from src.pos.cash.domain.entities import CashMovement, CashMovementType
from src.pos.cash.domain.exceptions import (
    InvalidCashMovementAmountError,
    ShiftNotOpenForCashMovementError,
)
from src.pos.shift.app.repositories import ShiftRepository
from src.pos.shift.domain.entities import ShiftStatus
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class RegisterCashMovementCommand(Command):
    shift_id: int
    type: str
    amount: Decimal
    reason: str | None = None
    performed_by: str | None = None


@injectable(lifetime="scoped")
class RegisterCashMovementCommandHandler(
    CommandHandler[RegisterCashMovementCommand, dict]
):
    def __init__(
        self,
        cash_repo: CashMovementRepository,
        shift_repo: ShiftRepository,
        audit: AuditTrail,
    ):
        self.cash_repo = cash_repo
        self.shift_repo = shift_repo
        self.audit = audit

    def _handle(self, command: RegisterCashMovementCommand) -> dict:
        if command.amount <= 0:
            raise InvalidCashMovementAmountError()

        shift = self.shift_repo.get_by_id(command.shift_id)
        if shift is None:
            raise NotFoundError(f"Shift with id {command.shift_id} not found")

        if shift.status != ShiftStatus.OPEN:
            raise ShiftNotOpenForCashMovementError(command.shift_id)

        movement = CashMovement(
            shift_id=command.shift_id,
            type=CashMovementType(command.type),
            amount=command.amount,
            reason=command.reason,
            performed_by=command.performed_by,
        )

        created = self.cash_repo.create(movement)
        self.audit.record(
            AuditAction.CASH_MOVEMENT_REGISTERED,
            created.require_id(),
            after={
                "shift_id": created.shift_id,
                "type": created.type,
                "amount": created.amount,
                "reason": created.reason,
            },
            branch_id=shift.branch_id,
        )
        return created.dict()
