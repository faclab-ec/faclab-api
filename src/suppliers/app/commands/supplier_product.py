from dataclasses import dataclass, replace
from decimal import Decimal

from wireup import injectable

from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError
from src.suppliers.app.repositories import SupplierProductRepository
from src.suppliers.domain.entities import SupplierProduct


@dataclass
class CreateSupplierProductCommand(Command):
    supplier_id: int = 0
    product_id: int = 0
    purchase_price: Decimal = Decimal("0")
    supplier_sku: str | None = None
    min_order_quantity: int = 1
    lead_time_days: int | None = None
    is_preferred: bool = False


@injectable(lifetime="scoped")
class CreateSupplierProductCommandHandler(
    CommandHandler[CreateSupplierProductCommand, dict]
):
    def __init__(self, repo: SupplierProductRepository):
        self.repo = repo

    def _handle(self, command: CreateSupplierProductCommand) -> dict:
        supplier_product = SupplierProduct(
            supplier_id=command.supplier_id,
            product_id=command.product_id,
            purchase_price=command.purchase_price,
            supplier_sku=command.supplier_sku,
            min_order_quantity=command.min_order_quantity,
            lead_time_days=command.lead_time_days,
            is_preferred=command.is_preferred,
        )
        supplier_product = self.repo.create(supplier_product)
        return supplier_product.dict()


@dataclass
class UpdateSupplierProductCommand(Command):
    id: int = 0
    product_id: int = 0
    purchase_price: Decimal = Decimal("0")
    supplier_sku: str | None = None
    min_order_quantity: int = 1
    lead_time_days: int | None = None
    is_preferred: bool = False


@injectable(lifetime="scoped")
class UpdateSupplierProductCommandHandler(
    CommandHandler[UpdateSupplierProductCommand, dict]
):
    def __init__(self, repo: SupplierProductRepository):
        self.repo = repo

    def _handle(self, command: UpdateSupplierProductCommand) -> dict:
        supplier_product = self.repo.get_by_id(command.id)
        if supplier_product is None:
            raise NotFoundError(f"Supplier product with id {command.id} not found")
        supplier_product = replace(
            supplier_product,
            product_id=command.product_id,
            purchase_price=command.purchase_price,
            supplier_sku=command.supplier_sku,
            min_order_quantity=command.min_order_quantity,
            lead_time_days=command.lead_time_days,
            is_preferred=command.is_preferred,
        )
        supplier_product = self.repo.update(supplier_product)
        return supplier_product.dict()


@dataclass
class DeleteSupplierProductCommand(Command):
    id: int = 0


@injectable(lifetime="scoped")
class DeleteSupplierProductCommandHandler(
    CommandHandler[DeleteSupplierProductCommand, None]
):
    def __init__(self, repo: SupplierProductRepository):
        self.repo = repo

    def _handle(self, command: DeleteSupplierProductCommand) -> None:
        self.repo.delete(command.id)
