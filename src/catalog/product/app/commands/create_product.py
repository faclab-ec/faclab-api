from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.events import ProductCreated
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.tax import TaxCode


@dataclass
class CreateProductCommand(Command):
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
class CreateProductCommandHandler(CommandHandler[CreateProductCommand, dict]):
    def __init__(self, repo: ProductRepository, event_publisher: EventPublisher):
        self.repo = repo
        self.event_publisher = event_publisher

    def _handle(self, command: CreateProductCommand) -> dict:
        product = Product(
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
        product = self.repo.create(product)

        self.event_publisher.publish(
            ProductCreated(
                aggregate_id=product.id,
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                category_id=product.category_id,
            )
        )

        return product.dict()
