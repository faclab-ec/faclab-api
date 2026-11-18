from dataclasses import dataclass

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.customers.app.repositories import CustomerRepository
from src.inventory.location.app.repositories import LocationRepository
from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.organization.app.repositories import BranchRepository, EmissionPointRepository
from src.organization.domain.exceptions import (
    BranchInactiveError,
    EmissionPointOutsideBranchError,
    LocationOutsideBranchError,
)
from src.pos.sales.app.checkout import SaleCheckout, SaleOrder, SalePlacement
from src.pos.sales.app.commands.cancel_sale import (
    POSCancelSaleCommand,
    POSCancelSaleCommandHandler,
)
from src.public_api.domain.exceptions import (
    CustomerInactiveError,
    EmissionPointInactiveError,
    LocationInactiveError,
    PaymentMethodNotAllowedError,
    ReferenceNotFoundError,
    SaleNotFromClientError,
)
from src.sales.app.repositories import SaleRepository
from src.sales.domain.entities import PaymentMethod, SaleChannel
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

# A sale of the API arrives paid online: no cash drawer takes it and nothing
# is left on credit
API_PAYMENT_METHODS = (
    PaymentMethod.CREDIT_CARD,
    PaymentMethod.DEBIT_CARD,
    PaymentMethod.TRANSFER,
    PaymentMethod.OTHER,
)


@dataclass
class CreateApiSaleCommand(Command):
    """A sale of an integration client, made and confirmed like the POS's quick
    sale at the branch, emission point and location it names"""

    integration_client_id: int
    branch_id: int
    emission_point_id: int
    location_id: int
    # [{"product_id", "quantity", "presentation_id"?, "unit_price"?,
    #   "override_reason"?, "discount"?}]
    items: list[dict]
    # [{"payment_method", "amount", "reference"?}]
    payments: list[dict]
    customer_id: int | None = None
    # The customer by its identification, when the client doesn't know its id
    identification: str | None = None
    external_reference: str | None = None
    notes: str | None = None
    created_by: str | None = None


@injectable(lifetime="scoped")
class CreateApiSaleCommandHandler(CommandHandler[CreateApiSaleCommand, dict]):
    def __init__(
        self,
        branches: BranchRepository,
        emission_points: EmissionPointRepository,
        locations: LocationRepository,
        warehouses: WarehouseRepository,
        customers: CustomerRepository,
        products: ProductRepository,
        checkout: SaleCheckout,
    ):
        self.branches = branches
        self.emission_points = emission_points
        self.locations = locations
        self.warehouses = warehouses
        self.customers = customers
        self.products = products
        self.checkout = checkout

    def _handle(self, command: CreateApiSaleCommand) -> dict:
        self._ensure_branch(command.branch_id)
        self._ensure_emission_point(command.emission_point_id, command.branch_id)
        self._ensure_location(command.location_id, command.branch_id)
        customer_id = self._customer(command)
        self._ensure_products(command.items)
        self._ensure_payment_methods(command.payments)

        return self.checkout.complete(
            SalePlacement(
                branch_id=command.branch_id,
                emission_point_id=command.emission_point_id,
                location_id=command.location_id,
                channel=SaleChannel.API,
                integration_client_id=command.integration_client_id,
                external_reference=command.external_reference,
            ),
            SaleOrder(
                items=command.items,
                payments=command.payments,
                customer_id=customer_id,
                notes=command.notes,
                created_by=command.created_by,
            ),
        )

    def _ensure_branch(self, branch_id: int) -> None:
        branch = self.branches.get_by_id(branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {branch_id} not found")
        if not branch.is_active:
            raise BranchInactiveError(branch_id)

    def _ensure_emission_point(self, emission_point_id: int, branch_id: int) -> None:
        point = self.emission_points.get_by_id(emission_point_id)
        if point is None:
            raise ReferenceNotFoundError(
                f"Emission point {emission_point_id} not found", "emissionPointId"
            )
        if point.branch_id != branch_id:
            raise EmissionPointOutsideBranchError()
        if not point.is_active:
            raise EmissionPointInactiveError(emission_point_id)

    def _ensure_location(self, location_id: int, branch_id: int) -> None:
        location = self.locations.get_by_id(location_id)
        if location is None:
            raise ReferenceNotFoundError(
                f"Location {location_id} not found", "locationId"
            )
        warehouse = self.warehouses.get_by_id(location.warehouse_id)
        if warehouse is None or warehouse.branch_id != branch_id:
            raise LocationOutsideBranchError()
        if not location.is_active or not warehouse.is_active:
            raise LocationInactiveError(location_id)

    def _customer(self, command: CreateApiSaleCommand) -> int | None:
        """The customer of the sale; none, the final consumer"""
        if command.customer_id is not None:
            customer = self.customers.get_by_id(command.customer_id)
            field_name = "customer.id"
        elif command.identification is not None:
            customer = self.customers.first(tax_id=command.identification)
            field_name = "customer.identification"
        else:
            return None
        if customer is None:
            raise ReferenceNotFoundError("Customer not found", field_name)
        if not customer.is_active:
            raise CustomerInactiveError(customer.require_id())
        return customer.require_id()

    def _ensure_products(self, items: list[dict]) -> None:
        ids = {item["product_id"] for item in items}
        found = {product.require_id() for product in self.products.get_by_ids(ids)}
        for index, item in enumerate(items):
            if item["product_id"] not in found:
                raise ReferenceNotFoundError(
                    f"Product {item['product_id']} not found",
                    f"items.{index}.productId",
                )

    @staticmethod
    def _ensure_payment_methods(payments: list[dict]) -> None:
        allowed = [method.value for method in API_PAYMENT_METHODS]
        for payment in payments:
            if payment["payment_method"] not in allowed:
                raise PaymentMethodNotAllowedError(payment["payment_method"], allowed)


@dataclass
class CancelApiSaleCommand(Command):
    integration_client_id: int
    sale_id: int
    reason: str | None = None
    # The client's branches; None, every one
    allowed_branch_ids: frozenset[int] | None = None


@injectable(lifetime="scoped")
class CancelApiSaleCommandHandler(CommandHandler[CancelApiSaleCommand, dict]):
    """Cancels a sale the same client created, under the rules of the POS:
    before its invoice is on its way (`INVOICE_IN_PROGRESS`) and, once
    invoiced, only with a credit note (`CREDIT_NOTE_REQUIRED`). Its stock goes
    back where it left from."""

    def __init__(self, sales: SaleRepository, cancel: POSCancelSaleCommandHandler):
        self.sales = sales
        self.cancel = cancel

    def _handle(self, command: CancelApiSaleCommand) -> dict:
        sale = self.sales.get_by_id(command.sale_id)
        if sale is None or (
            command.allowed_branch_ids is not None
            and sale.branch_id not in command.allowed_branch_ids
        ):
            raise NotFoundError(f"Sale with id {command.sale_id} not found")
        if sale.integration_client_id != command.integration_client_id:
            raise SaleNotFromClientError(command.sale_id)
        self.cancel.handle(
            POSCancelSaleCommand(
                sale_id=command.sale_id,
                reason=command.reason,
                source=SaleChannel.API.value,
            )
        )
        return {"sale_id": command.sale_id}
