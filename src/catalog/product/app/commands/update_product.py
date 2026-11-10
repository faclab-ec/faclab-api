from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
from src.catalog.product.domain.entities import Product
from src.catalog.product.domain.events import ProductUpdated
from src.catalog.product.domain.exceptions import UnitOfMeasureRequiredError
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import ConstructionMaterialCode, TaxCode

# A change of any of them is audited as a price change
PRICE_FIELDS = frozenset({"purchase_price", "sale_price", "tax_code"})


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
    construction_material_code: ConstructionMaterialCode | None = None
    is_active: bool = True
    is_service: bool = False
    min_stock: Decimal = Decimal(0)
    max_stock: Decimal | None = None
    reorder_point: Decimal = Decimal(0)
    lead_time_days: int | None = None


@injectable(lifetime="scoped")
class UpdateProductCommandHandler(CommandHandler[UpdateProductCommand, dict]):
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

    def _handle(self, command: UpdateProductCommand) -> dict:
        if command.unit_of_measure_id is None:
            raise UnitOfMeasureRequiredError()
        existing = self.repo.get_by_id(command.product_id)
        if existing is None:
            raise NotFoundError(f"Product with id {command.product_id} not found")
        old_barcode = self.presentations.base_barcode(command.product_id)

        product = Product(
            id=command.product_id,
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
        product = self.repo.update(product)
        # The base presentation follows the unit and carries the barcode (S5.2)
        self.presentations.sync_base(product, command.barcode)

        changes = {}
        if old_barcode != command.barcode:
            changes["barcode"] = {"old": old_barcode, "new": command.barcode}
        for field in (
            "sku",
            "name",
            "description",
            "category_id",
            "unit_of_measure_id",
            "purchase_price",
            "sale_price",
            "tax_code",
            "construction_material_code",
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

        if changes:
            self.audit.record(
                AuditAction.PRODUCT_PRICE_CHANGED
                if PRICE_FIELDS & changes.keys()
                else AuditAction.PRODUCT_UPDATED,
                product.require_id(),
                before={field: change["old"] for field, change in changes.items()},
                after={field: change["new"] for field, change in changes.items()},
            )

        self.event_publisher.publish(
            ProductUpdated(
                aggregate_id=product.require_id(),
                product_id=product.require_id(),
                changes=changes,
            )
        )

        [described] = self.presentations.describe(
            self.quantities.describe([product.dict()])
        )
        return described
