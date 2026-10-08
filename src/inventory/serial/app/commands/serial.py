from dataclasses import dataclass

from wireup import injectable

from src.inventory.serial.app.repositories import SerialNumberRepository
from src.inventory.serial.domain.entities import SerialNumber, SerialStatus
from src.inventory.serial.domain.exceptions import (
    InvalidSerialStatusError,
    SerialNumberAlreadyExistsError,
)
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError, ValidationError


@dataclass
class CreateSerialNumberCommand(Command):
    product_id: int = 0
    serial_number: str = ""
    lot_id: int | None = None
    location_id: int | None = None
    purchase_order_id: int | None = None
    notes: str | None = None


@dataclass
class UpdateSerialStatusCommand(Command):
    id: int = 0
    status: str = ""


@injectable(lifetime="scoped")
class CreateSerialNumberCommandHandler(CommandHandler[CreateSerialNumberCommand, dict]):
    def __init__(self, repo: SerialNumberRepository):
        self.repo = repo

    def _handle(self, command: CreateSerialNumberCommand) -> dict:
        existing = self.repo.first(serial_number=command.serial_number)
        if existing is not None:
            raise SerialNumberAlreadyExistsError(command.serial_number)

        serial = SerialNumber(
            product_id=command.product_id,
            serial_number=command.serial_number,
            status=SerialStatus.AVAILABLE,
            lot_id=command.lot_id,
            location_id=command.location_id,
            purchase_order_id=command.purchase_order_id,
            notes=command.notes,
        )
        serial = self.repo.create(serial)
        return serial.dict()


@injectable(lifetime="scoped")
class UpdateSerialStatusCommandHandler(CommandHandler[UpdateSerialStatusCommand, dict]):
    def __init__(self, repo: SerialNumberRepository):
        self.repo = repo

    def _handle(self, command: UpdateSerialStatusCommand) -> dict:
        serial = self.repo.get_by_id(command.id)
        if serial is None:
            raise NotFoundError(f"Serial number with id {command.id} not found")

        try:
            new_status = SerialStatus(command.status)
        except ValueError as err:
            raise ValidationError(
                f"Invalid serial status: '{command.status}'. "
                f"Valid values: {', '.join(s.value for s in SerialStatus)}"
            ) from err

        if new_status == SerialStatus.SOLD:
            serial = serial.mark_sold()
        elif new_status == SerialStatus.RESERVED:
            serial = serial.mark_reserved()
        elif new_status == SerialStatus.RETURNED:
            serial = serial.mark_returned()
        elif new_status == SerialStatus.SCRAPPED:
            serial = serial.mark_scrapped()
        else:
            raise InvalidSerialStatusError(
                serial.serial_number, serial.status, command.status
            )

        serial = self.repo.update(serial)
        return serial.dict()
