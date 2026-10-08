from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.events import ProductUpdated
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import TaxCode


@dataclass
class UpdateProductCommand(Command):
    product_id: int
    sku: str
    name: str
    description: str | None = None
    barcode: str | None = None
    category_id: int | None = None
    unit_of_measure_id: int | None = None
    purchase_price: Decimal | None = None
    sale_price: Decimal | None = None
    tax_code: TaxCode = TaxCode.VAT_15
    is_active: bool = True
    is_service: bool = False
    min_stock: int = 0
    max_stock: int | None = None
    reorder_point: int = 0
    lead_time_days: int | None = None


@injectable(lifetime="scoped")
class UpdateProductCommandHandler(CommandHandler[UpdateProductCommand, dict]):
    def __init__(self, repo: ProductRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: UpdateProductCommand) -> dict:
        existing = self.repo.get_by_id(command.product_id)
        if existing is None:
            raise NotFoundError(f"Product with id {command.product_id} not found")

        product = Product(
            id=command.product_id,
            sku=command.sku,
            name=command.name,
            description=command.description,
            barcode=command.barcode,
            category_id=command.category_id,
            unit_of_measure_id=command.unit_of_measure_id,
            purchase_price=command.purchase_price,
            sale_price=command.sale_price,
            tax_code=command.tax_code,
            is_active=command.is_active,
            is_service=command.is_service,
            min_stock=command.min_stock,
            max_stock=command.max_stock,
            reorder_point=command.reorder_point,
            lead_time_days=command.lead_time_days,
        )
        product = self.repo.update(product)

        changes = {}
        for field in (
            "sku",
            "name",
            "description",
            "barcode",
            "category_id",
            "unit_of_measure_id",
            "purchase_price",
            "sale_price",
            "tax_code",
            "is_active",
            "is_service",
            "min_stock",
            "max_stock",
            "reorder_point",
            "lead_time_days",
        ):
            old_val = getattr(existing, field)
            new_val = getattr(product, field)
            if old_val != new_val:
                changes[field] = {"old": old_val, "new": new_val}

        self.event_publisher.publish(
            ProductUpdated(
                aggregate_id=product.id,
                product_id=product.id,
                changes=changes,
            )
        )

        return product.dict()
