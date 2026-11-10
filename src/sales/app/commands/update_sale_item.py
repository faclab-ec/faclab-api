from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import ProductPresentations
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.pricing.app.resolver import PriceResolver
from src.sales.app.repositories import SaleItemRepository, SaleRepository
from src.sales.domain.entities import Sale, SaleItem
from src.sales.domain.exceptions import SaleItemNotInSaleError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class UpdateSaleItemCommand(Command):
    """Comando para actualizar un item de una venta"""

    sale_id: int
    sale_item_id: int
    quantity: Decimal | None = None
    discount: Decimal | None = None


@injectable(lifetime="scoped")
class UpdateSaleItemCommandHandler(CommandHandler[UpdateSaleItemCommand, dict]):
    """Handler para actualizar un item de una venta y recalcular totales.

    Una línea sin override que cambia de cantidad vuelve a tomar el precio de su
    lista, así la alcanza una escala por volumen (S5.3); una con override
    conserva su precio."""

    def __init__(
        self,
        sale_repo: SaleRepository,
        sale_item_repo: SaleItemRepository,
        quantities: ProductQuantities,
        products: ProductRepository,
        presentation_repo: ProductPresentationRepository,
        presentations: ProductPresentations,
        prices: PriceResolver,
    ):
        self.sale_repo = sale_repo
        self.sale_item_repo = sale_item_repo
        self.quantities = quantities
        self.products = products
        self.presentation_repo = presentation_repo
        self.presentations = presentations
        self.prices = prices

    def _handle(self, command: UpdateSaleItemCommand) -> dict:
        """Actualiza un item de la venta y recalcula los totales"""
        sale = self.sale_repo.get_by_id(command.sale_id)
        if not sale:
            raise NotFoundError(f"Sale with id {command.sale_id} not found")

        sale.ensure_draft("update items in")

        sale_item = self.sale_item_repo.get_by_id(command.sale_item_id)
        if not sale_item:
            raise NotFoundError(f"Sale item with id {command.sale_item_id} not found")

        if sale_item.sale_id != command.sale_id:
            raise SaleItemNotInSaleError(command.sale_item_id, command.sale_id)

        if command.quantity is not None:
            self.quantities.ensure_in_presentations(
                [(sale_item.product_id, sale_item.unit_factor, command.quantity)]
            )
            sale_item.quantity = command.quantity
            if sale_item.price_override is None:
                self._reprice(sale, sale_item)
        if command.discount is not None:
            sale_item.discount = command.discount

        sale_item.recalculate_tax()

        self.sale_item_repo.update(sale_item)

        # Recalcular totales de la venta
        items = self.sale_item_repo.filter_by(sale_id=command.sale_id)
        sale.recalculate_totals(items)
        self.sale_repo.update(sale)

        result = sale_item.dict()
        result["subtotal"] = sale_item.subtotal
        return result

    def _reprice(self, sale: Sale, item: SaleItem) -> None:
        """El precio de lista de la línea con su cantidad nueva"""
        product = self.products.get_by_id(item.product_id)
        if product is None:
            return
        # Its own presentation, even if it was deactivated after it was added
        presentation = (
            self.presentation_repo.get_by_id(item.presentation_id)
            if item.presentation_id is not None
            else None
        ) or self.presentations.resolve(product, None)
        chain = self.prices.chain(sale.customer_id, sale.branch_id)
        resolved = self.prices.price(chain, product, presentation, item.quantity)
        if resolved.unit_price is not None:
            item.unit_price = resolved.unit_price
