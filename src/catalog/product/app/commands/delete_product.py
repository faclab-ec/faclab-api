from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.commands.create_product import AUDITED_FIELDS
from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.events import ProductDeleted
from src.shared.app.audit import AuditAction, AuditTrail, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class DeleteProductCommand(Command):
    product_id: int


@injectable(lifetime="scoped")
class DeleteProductCommandHandler(CommandHandler[DeleteProductCommand, None]):
    def __init__(
        self,
        repo: ProductRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: DeleteProductCommand) -> None:
        existing = self.repo.get_by_id(command.product_id)
        self.repo.delete(command.product_id)
        if existing is not None:
            self.audit.record(
                AuditAction.PRODUCT_DELETED,
                command.product_id,
                before=snapshot(existing, *AUDITED_FIELDS),
            )

        self.event_publisher.publish(
            ProductDeleted(
                aggregate_id=command.product_id,
                product_id=command.product_id,
            )
        )
