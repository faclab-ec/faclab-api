from dataclasses import dataclass
from decimal import Decimal

from wireup import injectable

from src.catalog.product.app.presentations import presentation_view
from src.catalog.product.app.quantities import ProductQuantities
from src.catalog.product.app.repositories import (
    ProductPresentationRepository,
    ProductRepository,
)
from src.catalog.product.domain.entities import Product, ProductPresentation
from src.catalog.product.domain.exceptions import BasePresentationFixedError
from src.shared.app.audit import AuditAction, AuditTrail, changed, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

# What the audit log keeps of a presentation
AUDITED_FIELDS = (
    "name",
    "factor",
    "barcode",
    "sale_price",
    "purchase_price",
    "is_active",
)


def _product(products: ProductRepository, product_id: int) -> Product:
    product = products.get_by_id(product_id)
    if product is None:
        raise NotFoundError(f"Product with id {product_id} not found")
    return product


def _presentation(
    presentations: ProductPresentationRepository, product_id: int, presentation_id: int
) -> ProductPresentation:
    presentation = presentations.get_by_id(presentation_id)
    if presentation is None or presentation.product_id != product_id:
        raise NotFoundError(
            f"Presentation with id {presentation_id} of product {product_id} not found"
        )
    return presentation


def _view(
    quantities: ProductQuantities, product: Product, presentation: ProductPresentation
) -> dict:
    [described] = quantities.describe([product.dict()])
    return presentation_view(presentation, described)


def _audited(presentation: ProductPresentation) -> dict:
    return {"presentation_id": presentation.id, "name": presentation.name}


@dataclass
class CreateProductPresentationCommand(Command):
    product_id: int
    name: str
    factor: Decimal
    barcode: str | None = None
    sale_price: Decimal | None = None
    purchase_price: Decimal | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class CreateProductPresentationCommandHandler(
    CommandHandler[CreateProductPresentationCommand, dict]
):
    """Una presentación más del producto (la base la crean los comandos de producto)"""

    def __init__(
        self,
        products: ProductRepository,
        presentations: ProductPresentationRepository,
        quantities: ProductQuantities,
        audit: AuditTrail,
    ):
        self.products = products
        self.presentations = presentations
        self.quantities = quantities
        self.audit = audit

    def _handle(self, command: CreateProductPresentationCommand) -> dict:
        product = _product(self.products, command.product_id)
        presentation = ProductPresentation(
            product_id=product.require_id(),
            name=command.name,
            factor=command.factor,
            barcode=command.barcode,
            sale_price=command.sale_price,
            purchase_price=command.purchase_price,
            is_active=command.is_active,
        )
        # One presentation is `factor` base units: it must fit the unit
        self.quantities.ensure_for_product(product, presentation.factor)
        presentation = self.presentations.create(presentation)
        self.audit.record(
            AuditAction.PRODUCT_PRESENTATION_CREATED,
            product.require_id(),
            after=_audited(presentation) | snapshot(presentation, *AUDITED_FIELDS),
        )
        return _view(self.quantities, product, presentation)


@dataclass
class UpdateProductPresentationCommand(Command):
    product_id: int
    presentation_id: int
    name: str
    factor: Decimal
    barcode: str | None = None
    sale_price: Decimal | None = None
    purchase_price: Decimal | None = None
    is_active: bool = True


@injectable(lifetime="scoped")
class UpdateProductPresentationCommandHandler(
    CommandHandler[UpdateProductPresentationCommand, dict]
):
    """Reemplaza una presentación; de la base solo cambia el código de barras"""

    def __init__(
        self,
        products: ProductRepository,
        presentations: ProductPresentationRepository,
        quantities: ProductQuantities,
        audit: AuditTrail,
    ):
        self.products = products
        self.presentations = presentations
        self.quantities = quantities
        self.audit = audit

    def _handle(self, command: UpdateProductPresentationCommand) -> dict:
        product = _product(self.products, command.product_id)
        presentation = _presentation(
            self.presentations, command.product_id, command.presentation_id
        )
        before = snapshot(presentation, *AUDITED_FIELDS)
        presentation.change(
            name=command.name,
            factor=command.factor,
            barcode=command.barcode,
            sale_price=command.sale_price,
            purchase_price=command.purchase_price,
            is_active=command.is_active,
        )
        self.quantities.ensure_for_product(product, presentation.factor)
        presentation = self.presentations.update(presentation)
        old, new = changed(before, snapshot(presentation, *AUDITED_FIELDS))
        if new:
            self.audit.record(
                AuditAction.PRODUCT_PRESENTATION_UPDATED,
                product.require_id(),
                before=_audited(presentation) | old,
                after=_audited(presentation) | new,
            )
        return _view(self.quantities, product, presentation)


@dataclass
class DeleteProductPresentationCommand(Command):
    product_id: int
    presentation_id: int


@injectable(lifetime="scoped")
class DeleteProductPresentationCommandHandler(
    CommandHandler[DeleteProductPresentationCommand, None]
):
    """Borra una presentación que ninguna línea usa (si alguna la usa, 409
    RECORD_IN_USE: se desactiva). La base no se borra."""

    def __init__(self, presentations: ProductPresentationRepository, audit: AuditTrail):
        self.presentations = presentations
        self.audit = audit

    def _handle(self, command: DeleteProductPresentationCommand) -> None:
        presentation = _presentation(
            self.presentations, command.product_id, command.presentation_id
        )
        if presentation.is_base:
            raise BasePresentationFixedError("The base presentation can't be deleted")
        self.presentations.delete(presentation.require_id())
        self.audit.record(
            AuditAction.PRODUCT_PRESENTATION_DELETED,
            command.product_id,
            before=_audited(presentation) | snapshot(presentation, *AUDITED_FIELDS),
        )
