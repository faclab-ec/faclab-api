from dataclasses import dataclass

from wireup import injectable

from src.customers.domain.entities import TaxType
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.value_objects import Email, TaxId
from src.suppliers.app.repositories import SupplierRepository
from src.suppliers.domain.entities import Supplier
from src.suppliers.domain.events import (
    SupplierActivated,
    SupplierCreated,
    SupplierDeactivated,
)


@dataclass
class CreateSupplierCommand(Command):
    name: str = ""
    tax_id: str = ""
    tax_type: int = 1
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    payment_terms: int | None = None
    lead_time_days: int | None = None
    is_active: bool = True
    notes: str | None = None


@injectable(lifetime="scoped")
class CreateSupplierCommandHandler(CommandHandler[CreateSupplierCommand, dict]):
    def __init__(self, repo: SupplierRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CreateSupplierCommand) -> dict:
        if command.email:
            Email(command.email)
        if command.tax_type in (TaxType.RUC, TaxType.NATIONAL_ID):
            TaxId(command.tax_id)

        supplier = Supplier(
            name=command.name,
            tax_id=command.tax_id,
            tax_type=TaxType(command.tax_type),
            email=command.email,
            phone=command.phone,
            address=command.address,
            city=command.city,
            country=command.country,
            payment_terms=command.payment_terms,
            lead_time_days=command.lead_time_days,
            is_active=command.is_active,
            notes=command.notes,
        )
        supplier = self.repo.create(supplier)

        self.event_publisher.publish(
            SupplierCreated(
                aggregate_id=supplier.require_id(),
                supplier_id=supplier.require_id(),
                name=supplier.name,
                tax_id=supplier.tax_id,
            )
        )
        return supplier.dict()


@dataclass
class UpdateSupplierCommand(Command):
    id: int = 0
    name: str = ""
    tax_id: str = ""
    tax_type: int = 1
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    payment_terms: int | None = None
    lead_time_days: int | None = None
    is_active: bool = True
    notes: str | None = None


@injectable(lifetime="scoped")
class UpdateSupplierCommandHandler(CommandHandler[UpdateSupplierCommand, dict]):
    def __init__(self, repo: SupplierRepository):
        self.repo = repo

    def _handle(self, command: UpdateSupplierCommand) -> dict:
        if command.email:
            Email(command.email)
        if command.tax_type in (TaxType.RUC, TaxType.NATIONAL_ID):
            TaxId(command.tax_id)

        supplier = Supplier(
            id=command.id,
            name=command.name,
            tax_id=command.tax_id,
            tax_type=TaxType(command.tax_type),
            email=command.email,
            phone=command.phone,
            address=command.address,
            city=command.city,
            country=command.country,
            payment_terms=command.payment_terms,
            lead_time_days=command.lead_time_days,
            is_active=command.is_active,
            notes=command.notes,
        )
        supplier = self.repo.update(supplier)
        return supplier.dict()


@dataclass
class DeleteSupplierCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeleteSupplierCommandHandler(CommandHandler[DeleteSupplierCommand, None]):
    def __init__(self, repo: SupplierRepository):
        self.repo = repo

    def _handle(self, command: DeleteSupplierCommand) -> None:
        self.repo.delete(command.id)


@dataclass
class ActivateSupplierCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class ActivateSupplierCommandHandler(CommandHandler[ActivateSupplierCommand, dict]):
    def __init__(self, repo: SupplierRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: ActivateSupplierCommand) -> dict:
        supplier = self.repo.get_by_id(command.id)
        if supplier is None:
            raise NotFoundError(f"Supplier with id {command.id} not found")

        supplier.activate()
        updated_supplier = self.repo.update(supplier)

        self.event_publisher.publish(
            SupplierActivated(
                aggregate_id=updated_supplier.require_id(),
                supplier_id=updated_supplier.require_id(),
            )
        )
        return updated_supplier.dict()


@dataclass
class DeactivateSupplierCommand(Command):
    id: int = 0
    reason: str | None = None


@injectable(lifetime="scoped")
class DeactivateSupplierCommandHandler(CommandHandler[DeactivateSupplierCommand, dict]):
    def __init__(self, repo: SupplierRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: DeactivateSupplierCommand) -> dict:
        supplier = self.repo.get_by_id(command.id)
        if supplier is None:
            raise NotFoundError(f"Supplier with id {command.id} not found")

        supplier.deactivate()
        updated_supplier = self.repo.update(supplier)

        self.event_publisher.publish(
            SupplierDeactivated(
                aggregate_id=updated_supplier.require_id(),
                supplier_id=updated_supplier.require_id(),
                reason=command.reason,
            )
        )
        return updated_supplier.dict()
