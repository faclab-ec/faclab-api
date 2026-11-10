from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.events import ProductCreated
from src.catalog.product.domain.exceptions import UnitOfMeasureRequiredError
from src.shared.app.audit import AuditAction, AuditTrail, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.tax import ConstructionMaterialCode, TaxCode

# What the audit log keeps of a product that is created or deleted
AUDITED_FIELDS = (
    "sku",
    "name",
    "purchase_price",
    "sale_price",
    "tax_code",
    "construction_material_code",
    "is_active",
)


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
    construction_material_code: ConstructionMaterialCode | None = None
    is_active: bool = True
    is_service: bool = False
    min_stock: Decimal = Decimal(0)
    max_stock: Decimal | None = None
    reorder_point: Decimal = Decimal(0)
    lead_time_days: int | None = None


@injectable(lifetime="scoped")
class CreateProductCommandHandler(CommandHandler[CreateProductCommand, dict]):
    def __init__(
        self,
        repo: ProductRepository,
        event_publisher: EventPublisher,
        audit: AuditTrail,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
    ):
        self.repo = repo
        self.quantities = quantities
        self.presentations = presentations
        self.event_publisher = event_publisher
        self.audit = audit

    def _handle(self, command: CreateProductCommand) -> dict:
        if command.unit_of_measure_id is None:
            raise UnitOfMeasureRequiredError()
        product = Product(
            sku=command.sku,
            name=command.name,
            description=command.description,
            category_id=command.category_id,
            unit_of_measure_id=command.unit_of_measure_id,
            purchase_price=command.purchase_price,
            sale_price=command.sale_price,
            tax_code=command.tax_code,
            construction_material_code=command.construction_material_code,
            is_active=command.is_active,
            is_service=command.is_service,
            min_stock=command.min_stock,
            max_stock=command.max_stock,
            reorder_point=command.reorder_point,
            lead_time_days=command.lead_time_days,
        )
        product.ensure_material_tax()
        self.quantities.ensure_for_unit(
            product.unit_of_measure_id,
            (product.min_stock, product.max_stock, product.reorder_point),
        )
        product = self.repo.create(product)
        # Its base presentation: the unit, with the product's barcode (S5.2)
        self.presentations.create_base(product, command.barcode)
        self.audit.record(
            AuditAction.PRODUCT_CREATED,
            product.require_id(),
            after=snapshot(product, *AUDITED_FIELDS),
        )

        self.event_publisher.publish(
            ProductCreated(
                aggregate_id=product.require_id(),
                product_id=product.require_id(),
                sku=product.sku,
                name=product.name,
                category_id=product.category_id,
            )
        )

        [described] = self.presentations.describe(
            self.quantities.describe([product.dict()])
        )
        return described
