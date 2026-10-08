from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import CategoryRepository
from src.catalog.product.domain.entities import Category
from src.catalog.product.domain.events import CategoryUpdated
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateCategoryCommand(Command):
    category_id: int
    name: str
    description: str | None = None


@injectable(lifetime="scoped")
class UpdateCategoryCommandHandler(CommandHandler[UpdateCategoryCommand, dict]):
    def __init__(self, repo: CategoryRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: UpdateCategoryCommand) -> dict:
        # Get existing category to track changes
        existing = self.repo.get_by_id(command.category_id)
        if existing is None:
            raise NotFoundError(f"Category with id {command.category_id} not found")

        category = Category(
            id=command.category_id,
            name=command.name,
            description=command.description,
        )
        category = self.repo.update(category)

        # Track what changed
        changes = {}
        if existing.name != category.name:
            changes["name"] = {"old": existing.name, "new": category.name}
        if existing.description != category.description:
            changes["description"] = {
                "old": existing.description,
                "new": category.description,
            }

        self.event_publisher.publish(
            CategoryUpdated(
                aggregate_id=category.require_id(),
                category_id=category.require_id(),
                changes=changes,
            )
        )

        return category.dict()
