"""Writes of products and customers through the public API (S6.3): the same
commands as the internal API, with the fields an integration doesn't see (the
cost, stock thresholds, credit) kept as they are."""

from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.commands.update_product import (
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.commands.customer import (
    CreateCustomerCommand,
    CreateCustomerCommandHandler,
    UpdateCustomerCommand,
    UpdateCustomerCommandHandler,
)
from src.customers.app.repositories import CustomerRepository
from src.public_api.domain.exceptions import CustomerAlreadyExistsError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tax import ConstructionMaterialCode, TaxCode


@dataclass
class UpdateApiProductCommand(Command):
    product_id: int
    sku: str
    name: str
    unit_of_measure_id: int
    description: str | None = None
    category_id: int | None = None
    sale_price: Decimal | None = None
    tax_code: TaxCode = TaxCode.VAT_15
    construction_material_code: ConstructionMaterialCode | None = None
    barcode: str | None = None
    is_active: bool = True
    is_service: bool = False


@injectable(lifetime="scoped")
class UpdateApiProductCommandHandler(CommandHandler[UpdateApiProductCommand, dict]):
    def __init__(
        self, products: ProductRepository, update: UpdateProductCommandHandler
    ):
        self.products = products
        self.update = update

    def _handle(self, command: UpdateApiProductCommand) -> dict:
        current = self.products.get_by_id(command.product_id)
        if current is None:
            raise NotFoundError(f"Product with id {command.product_id} not found")
        return self.update.handle(
            UpdateProductCommand(
                product_id=command.product_id,
                sku=command.sku,
                name=command.name,
                description=command.description,
                barcode=command.barcode,
                category_id=command.category_id,
                unit_of_measure_id=command.unit_of_measure_id,
                sale_price=command.sale_price,
                tax_code=command.tax_code,
                construction_material_code=command.construction_material_code,
                is_active=command.is_active,
                is_service=command.is_service,
                # Not in the public API
                purchase_price=current.purchase_price,
                min_stock=current.min_stock,
                max_stock=current.max_stock,
                reorder_point=current.reorder_point,
                lead_time_days=current.lead_time_days,
            )
        )


@dataclass
class SaveApiCustomerCommand(Command):
    name: str
    tax_id: str
    tax_type: int
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    is_active: bool = True
    # None: a new one
    customer_id: int | None = None


@injectable(lifetime="scoped")
class SaveApiCustomerCommandHandler(CommandHandler[SaveApiCustomerCommand, dict]):
    """Creates a customer, or replaces the editable fields of one. A new one
    with the identification of another answers `CUSTOMER_ALREADY_EXISTS` with
    its id, so the integration links it instead"""

    def __init__(
        self,
        customers: CustomerRepository,
        create: CreateCustomerCommandHandler,
        update: UpdateCustomerCommandHandler,
    ):
        self.customers = customers
        self.create = create
        self.update = update

    def _handle(self, command: SaveApiCustomerCommand) -> dict:
        if command.customer_id is None:
            existing = self.customers.first(tax_id=command.tax_id)
            if existing is not None:
                raise CustomerAlreadyExistsError(existing.require_id())
            return self.create.handle(
                CreateCustomerCommand(
                    name=command.name,
                    tax_id=command.tax_id,
                    tax_type=command.tax_type,
                    email=command.email,
                    phone=command.phone,
                    address=command.address,
                    city=command.city,
                    state=command.state,
                    country=command.country,
                    is_active=command.is_active,
                )
            )

        current = self.customers.get_by_id(command.customer_id)
        if current is None:
            raise NotFoundError(f"Customer with id {command.customer_id} not found")
        return self.update.handle(
            UpdateCustomerCommand(
                id=command.customer_id,
                name=command.name,
                tax_id=command.tax_id,
                tax_type=command.tax_type,
                email=command.email,
                phone=command.phone,
                address=command.address,
                city=command.city,
                state=command.state,
                country=command.country,
                is_active=command.is_active,
                # Credit is not in the public API
                credit_limit=current.credit_limit,
                payment_terms=current.payment_terms,
            )
        )
