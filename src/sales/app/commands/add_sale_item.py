from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import ProductRepository
from src.pricing.app.resolver import PriceResolver
from src.sales.app.price_override import audit_price_override
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import SaleItem
from src.sales.domain.events import SaleItemAdded
from src.sales.domain.pricing import line_price
from src.shared.app.audit import AuditTrail
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class AddSaleItemCommand(Command):
    """Comando para agregar un item a una venta"""

    sale_id: int
    product_id: int
    quantity: Decimal
    # None: the price of its list (S5.3). Another one is an override: it needs
    # `override_reason` and goes to the audit log
    unit_price: Decimal | None = None
    discount: Decimal = Decimal("0")
    # The presentation it is sold in (S5.2); none: the base unit
    presentation_id: int | None = None
    override_reason: str | None = None


@injectable(lifetime="scoped")
class AddSaleItemCommandHandler(CommandHandler[AddSaleItemCommand, dict]):
    """Handler para agregar un item a una venta y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        product_repo: ProductRepository,
        event_publisher: EventPublisher,
        quantities: ProductQuantities,
        presentations: ProductPresentations,
        prices: PriceResolver,
        audit: AuditTrail,
    ):
        self.presentations = presentations
        self.prices = prices
        self.audit = audit
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.product_repo = product_repo
        self.event_publisher = event_publisher
        self.quantities = quantities

    def _handle(self, command: AddSaleItemCommand) -> dict:
        """Agrega un item a la venta y recalcula los totales"""
        # Obtener la venta
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        # Validar que la venta esté en DRAFT
        sale.ensure_draft("add items to")

        # Obtener tax_code del producto
        product = self.product_repo.get_by_id(command.product_id)
        if not product:
            raise NotFoundError(f"Product with id {command.product_id} not found")
        presentation = self.presentations.resolve(product, command.presentation_id)
        self.quantities.ensure_for_presentation(
            product, presentation.factor, command.quantity
        )
        quantity = Decimal(command.quantity)

        # El precio de su lista: la del cliente, la de la sucursal o la general
        chain = self.prices.chain(sale.customer_id, sale.branch_id)
        list_price = self.prices.price(chain, product, presentation, quantity)
        unit_price, overridden = line_price(
            product.require_id(),
            list_price.unit_price,
            command.unit_price,
            command.override_reason,
        )

        # Crear el item con el IVA de su producto, en su presentación
        sale_item = SaleItem(
            sale_id=command.sale_id,
            product_id=command.product_id,
            quantity=quantity,
            unit_price=unit_price,
            discount=Decimal(str(command.discount)),
            tax_code=product.tax_code,
            price_override=unit_price if overridden else None,
            override_reason=command.override_reason if overridden else None,
            presentation_id=presentation.id,
            unit_factor=presentation.factor,
        )
        sale_item.recalculate_tax()

        sale_item = self.sale_item_repo.create(sale_item)
        if overridden:
            audit_price_override(self.audit, sale, sale_item, list_price.unit_price)

        # Recalcular totales de la venta
        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        # Publicar evento
        self.event_publisher.publish(
            SaleItemAdded(
                aggregate_id=sale.require_id(),
                sale_id=sale.require_id(),
                sale_item_id=sale_item.require_id(),
                product_id=sale_item.product_id,
                quantity=sale_item.quantity,
                unit_price=sale_item.unit_price,
            )
        )

        # Incluir el subtotal calculado en la respuesta
        result = sale_item.dict()
        result["subtotal"] = sale_item.subtotal
        return result
