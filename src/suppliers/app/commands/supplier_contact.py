from dataclasses import dataclass, replace

from wireup import injectable

from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError
from src.suppliers.app.repositories import SupplierContactRepository
from src.suppliers.domain.entities import SupplierContact


@dataclass
class CreateSupplierContactCommand(Command):
    supplier_id: int = 0
    name: str = ""
    role: str | None = None
    email: str | None = None
    phone: str | None = None


@injectable(lifetime="scoped")
class CreateSupplierContactCommandHandler(
    CommandHandler[CreateSupplierContactCommand, dict]
):
    def __init__(self, repo: SupplierContactRepository):
        self.repo = repo

    def _handle(self, command: CreateSupplierContactCommand) -> dict:
        contact = SupplierContact(
            supplier_id=command.supplier_id,
            name=command.name,
            role=command.role,
            email=command.email,
            phone=command.phone,
        )
        contact = self.repo.create(contact)
        return contact.dict()


@dataclass
class UpdateSupplierContactCommand(Command):
    id: int = 0
    name: str = ""
    role: str | None = None
    email: str | None = None
    phone: str | None = None


@injectable(lifetime="scoped")
class UpdateSupplierContactCommandHandler(
    CommandHandler[UpdateSupplierContactCommand, dict]
):
    def __init__(self, repo: SupplierContactRepository):
        self.repo = repo

    def _handle(self, command: UpdateSupplierContactCommand) -> dict:
        contact = self.repo.get_by_id(command.id)
        if contact is None:
            raise NotFoundError(f"Supplier contact with id {command.id} not found")
        contact = replace(
            contact,
            name=command.name,
            role=command.role,
            email=command.email,
            phone=command.phone,
        )
        contact = self.repo.update(contact)
        return contact.dict()


@dataclass
class DeleteSupplierContactCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeleteSupplierContactCommandHandler(
    CommandHandler[DeleteSupplierContactCommand, None]
):
    def __init__(self, repo: SupplierContactRepository):
        self.repo = repo

    def _handle(self, command: DeleteSupplierContactCommand) -> None:
        self.repo.delete(command.id)
