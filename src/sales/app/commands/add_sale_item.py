from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.repositories import ProductRepository
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import SaleItem
from src.sales.domain.events import SaleItemAdded
from src.shared.app.commands import Command, CommandHandler
from src.shared.app.events import EventPublisher
from src.shared.domain.exceptions import NotFoundError


@dataclass
class AddSaleItemCommand(Command):
    """Comando para agregar un item a una venta"""

    sale_id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    discount: Decimal = Decimal("0")


@injectable(lifetime="scoped")
class AddSaleItemCommandHandler(CommandHandler[AddSaleItemCommand, dict]):
    """Handler para agregar un item a una venta y recalcular totales"""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        product_repo: ProductRepository,
        event_publisher: EventPublisher,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.product_repo = product_repo
        self.event_publisher = event_publisher

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

        # Crear el item con el IVA de su producto
        sale_item = SaleItem(
            sale_id=command.sale_id,
            product_id=command.product_id,
            quantity=command.quantity,
            unit_price=Decimal(str(command.unit_price)),
            discount=Decimal(str(command.discount)),
            tax_code=product.tax_code,
        )
        sale_item.recalculate_tax()

        sale_item = self.sale_item_repo.create(sale_item)

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
