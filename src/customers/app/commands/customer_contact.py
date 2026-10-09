from dataclasses import dataclass

from wireup import injectable

from src.customers.app.repositories import CustomerContactRepository
from src.customers.domain.entities import CustomerContact
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateCustomerContactCommand(Command):
    customer_id: int = 0
    name: str = ""
    role: str | None = None
    email: str | None = None
    phone: str | None = None


@injectable(lifetime="scoped")
class CreateCustomerContactCommandHandler(
    CommandHandler[CreateCustomerContactCommand, dict]
):
    def __init__(self, repo: CustomerContactRepository):
        self.repo = repo

    def _handle(self, command: CreateCustomerContactCommand) -> dict:
        contact = CustomerContact(
            customer_id=command.customer_id,
            name=command.name,
            role=command.role,
            email=command.email,
            phone=command.phone,
        )
        contact = self.repo.create(contact)
        return contact.dict()


@dataclass
class UpdateCustomerContactCommand(Command):
    id: int = 0
    name: str = ""
    role: str | None = None
    email: str | None = None
    phone: str | None = None


@injectable(lifetime="scoped")
class UpdateCustomerContactCommandHandler(
    CommandHandler[UpdateCustomerContactCommand, dict]
):
    def __init__(self, repo: CustomerContactRepository):
        self.repo = repo

    def _handle(self, command: UpdateCustomerContactCommand) -> dict:
        contact = self.repo.get_by_id(command.id)
        if contact is None:
            raise NotFoundError(f"Customer contact with id {command.id} not found")
        contact.update(
            name=command.name,
            role=command.role,
            email=command.email,
            phone=command.phone,
        )
        contact = self.repo.update(contact)
        return contact.dict()


@dataclass
class DeleteCustomerContactCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeleteCustomerContactCommandHandler(
    CommandHandler[DeleteCustomerContactCommand, None]
):
    def __init__(self, repo: CustomerContactRepository):
        self.repo = repo

    def _handle(self, command: DeleteCustomerContactCommand) -> None:
        self.repo.delete(command.id)
