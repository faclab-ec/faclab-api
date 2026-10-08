from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import CategoryRepository
from src.catalog.product.domain.entities import Category
from src.catalog.product.domain.events import CategoryCreated
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher


@dataclass
class CreateCategoryCommand(Command):
    name: str
    description: str | None = None


@injectable(lifetime="scoped")
class CreateCategoryCommandHandler(CommandHandler[CreateCategoryCommand, dict]):
    def __init__(self, repo: CategoryRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CreateCategoryCommand) -> dict:
        category = Category(
            name=command.name,
            description=command.description,
        )
        category = self.repo.create(category)

        self.event_publisher.publish(
            CategoryCreated(
                aggregate_id=category.require_id(),
                category_id=category.require_id(),
                name=category.name,
            )
        )

        return category.dict()
