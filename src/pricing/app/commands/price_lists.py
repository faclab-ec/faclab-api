from dataclasses import dataclass
from datetime import date

from wireup import injectable

from src.pricing.app.repositories import PriceListRepository
from src.pricing.domain.entities import PriceList
from src.shared.app.audit import AuditAction, AuditTrail, changed, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

# What the audit log keeps of a price list
AUDITED_FIELDS = ("name", "description", "is_active", "valid_from", "valid_to")
# The list every company has (S5.3): quantity tiers over the product's price
DEFAULT_PRICE_LIST_NAME = "General"


def ensure_default_price_list(lists: PriceListRepository) -> PriceList:
    """La lista general de la empresa, creada si todavía no la tiene (provisión)"""
    default = lists.default()
    if default is None:
        default = lists.create(PriceList(name=DEFAULT_PRICE_LIST_NAME, is_default=True))
    return default


def price_list_of(lists: PriceListRepository, price_list_id: int) -> PriceList:
    price_list = lists.get_by_id(price_list_id)
    if price_list is None:
        raise NotFoundError(f"Price list with id {price_list_id} not found")
    return price_list


@dataclass
class CreatePriceListCommand(Command):
    name: str
    description: str | None = None
    is_active: bool = True
    valid_from: date | None = None
    valid_to: date | None = None


@injectable(lifetime="scoped")
class CreatePriceListCommandHandler(CommandHandler[CreatePriceListCommand, dict]):
    """Una lista nueva (la general la crean la migración y la provisión)"""

    def __init__(self, lists: PriceListRepository, audit: AuditTrail):
        self.lists = lists
        self.audit = audit

    def _handle(self, command: CreatePriceListCommand) -> dict:
        price_list = self.lists.create(
            PriceList(
                name=command.name,
                description=command.description,
                is_active=command.is_active,
                valid_from=command.valid_from,
                valid_to=command.valid_to,
            )
        )
        self.audit.record(
            AuditAction.PRICE_LIST_CREATED,
            price_list.require_id(),
            after=snapshot(price_list, *AUDITED_FIELDS),
        )
        return price_list.dict()


@dataclass
class UpdatePriceListCommand(Command):
    price_list_id: int
    name: str
    description: str | None = None
    is_active: bool = True
    valid_from: date | None = None
    valid_to: date | None = None


@injectable(lifetime="scoped")
class UpdatePriceListCommandHandler(CommandHandler[UpdatePriceListCommand, dict]):
    """Reemplaza los datos de una lista; la general siempre queda activa y sin
    vigencia"""

    def __init__(self, lists: PriceListRepository, audit: AuditTrail):
        self.lists = lists
        self.audit = audit

    def _handle(self, command: UpdatePriceListCommand) -> dict:
        price_list = price_list_of(self.lists, command.price_list_id)
        previous = snapshot(price_list, *AUDITED_FIELDS)
        price_list.change(
            name=command.name,
            description=command.description,
            is_active=command.is_active,
            valid_from=command.valid_from,
            valid_to=command.valid_to,
        )
        price_list = self.lists.update(price_list)
        before, after = changed(previous, snapshot(price_list, *AUDITED_FIELDS))
        if after:
            self.audit.record(
                AuditAction.PRICE_LIST_UPDATED,
                command.price_list_id,
                before=before,
                after=after,
            )
        return price_list.dict()


@dataclass
class DeletePriceListCommand(Command):
    price_list_id: int


@injectable(lifetime="scoped")
class DeletePriceListCommandHandler(CommandHandler[DeletePriceListCommand, None]):
    """Borra una lista con sus ítems. Una asignada a un cliente o a una sucursal
    responde 409 RECORD_IN_USE: se desactiva o se quita la asignación. La
    general no se borra."""

    def __init__(self, lists: PriceListRepository, audit: AuditTrail):
        self.lists = lists
        self.audit = audit

    def _handle(self, command: DeletePriceListCommand) -> None:
        price_list = price_list_of(self.lists, command.price_list_id)
        price_list.ensure_deletable()
        self.lists.delete(command.price_list_id)
        self.audit.record(
            AuditAction.PRICE_LIST_DELETED,
            command.price_list_id,
            before=snapshot(price_list, *AUDITED_FIELDS),
        )
