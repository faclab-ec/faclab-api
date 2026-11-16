"""Presentaciones de un producto (S5.8): caja de 100, rollo de 50 m. Se
identifican por el SKU y su nombre; la base (la unidad) se carga con el
producto."""

from wireup import injectable

from src.catalog.product.app.commands.presentations import (
    CreateProductPresentationCommand,
    CreateProductPresentationCommandHandler,
    UpdateProductPresentationCommand,
    UpdateProductPresentationCommandHandler,
)
from src.imports.app.columns import Column, boolean, money, positive_quantity, text
from src.imports.app.kinds.base import (
    ALREADY_IN_USE,
    NOT_ALLOWED,
    NOT_FOUND,
    KindImporter,
    RowPlan,
)
from src.imports.app.lookups import ImportLookups, key
from src.imports.domain.entities import ImportJob, ImportKind, ImportMode

SKU = Column(
    "sku",
    "sku",
    "SKU del producto (debe existir)",
    "TOR-0001",
    key=True,
    required=True,
    parse=text(64),
)
NAME = Column(
    "presentacion",
    "name",
    "Nombre de la presentación, único en el producto",
    "Caja x100",
    key=True,
    required=True,
    parse=text(64),
)
FACTOR = Column(
    "factor",
    "factor",
    "Cuántas unidades base contiene",
    "100",
    required=True,
    parse=positive_quantity,
)
BARCODE = Column(
    "codigo_barras",
    "barcode",
    "Código de barras de la presentación, único en la empresa",
    "7861234500028",
    parse=text(64),
)
SALE_PRICE = Column(
    "precio_venta",
    "sale_price",
    "Precio de la presentación sin IVA; vacía: factor × el del producto",
    "13.50",
    parse=money,
)
PURCHASE_PRICE = Column(
    "precio_compra",
    "purchase_price",
    "Costo de la presentación sin IVA; vacía: factor × el del producto",
    "",
    parse=money,
)
IS_ACTIVE = Column(
    "activo", "is_active", "NO para dejarla inactiva", "SI", parse=boolean
)

_FIELDS = (FACTOR, BARCODE, SALE_PRICE, PURCHASE_PRICE, IS_ACTIVE)


@injectable(lifetime="scoped")
class PresentationImporter(KindImporter):
    kind = ImportKind.PRESENTATIONS
    columns = (SKU, NAME, FACTOR, BARCODE, SALE_PRICE, PURCHASE_PRICE, IS_ACTIVE)

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreateProductPresentationCommandHandler,
        update: UpdateProductPresentationCommandHandler,
    ):
        self.lookups = lookups
        self.create = create
        self.update = update

    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        self.unique_in_file(
            plans, lambda p: (p.get(SKU), key(p.get(NAME))), NAME, "La presentación"
        )
        self.unique_in_file(plans, lambda p: p.get(BARCODE), BARCODE, "El código")
        plans = [plan for plan in plans if plan.ok]
        products = self.lookups.products(plan.get(SKU) for plan in plans)
        presentations = self.lookups.presentations(
            product.require_id() for product in products.values()
        )
        units = {unit.id: unit for unit in self.lookups.units().values()}
        owners = self.lookups.barcodes(
            plan.get(BARCODE) for plan in plans if plan.has(BARCODE)
        )

        for plan in plans:
            product = products.get(plan.get(SKU))
            if product is None:
                plan.error(
                    SKU, NOT_FOUND, f"No existe un producto con SKU {plan.get(SKU)}"
                )
                continue
            existing = next(
                (
                    p
                    for p in presentations.get(product.require_id(), [])
                    if key(p.name) == key(plan.get(NAME))
                ),
                None,
            )
            if existing is not None and existing.is_base:
                plan.error(
                    NAME,
                    NOT_ALLOWED,
                    "Es la presentación base: su código de barras se carga en la "
                    "plantilla de productos",
                )
                continue
            if existing is not None:
                plan.target_id = existing.id
                if mode == ImportMode.SKIP:
                    self.settle(plan, mode, changed=False)
                    continue
                current = {
                    "name": existing.name,
                    "factor": existing.factor,
                    "barcode": existing.barcode,
                    "sale_price": existing.sale_price,
                    "purchase_price": existing.purchase_price,
                    "is_active": existing.is_active,
                }
            elif not self.require(plan, FACTOR):
                continue
            else:
                current = {
                    "name": plan.get(NAME),
                    "barcode": None,
                    "sale_price": None,
                    "purchase_price": None,
                    "is_active": True,
                }

            payload = dict(current)
            for column in _FIELDS:
                if plan.has(column):
                    payload[column.field] = plan.get(column)

            unit = units.get(product.unit_of_measure_id or 0)
            if unit is not None:
                self.fits_decimals(
                    plan, FACTOR, payload["factor"], unit.decimals, unit.symbol
                )
            if plan.has(BARCODE):
                owner = owners.get(plan.get(BARCODE))
                if owner is not None and owner.id != plan.target_id:
                    plan.error(
                        BARCODE,
                        ALREADY_IN_USE,
                        "Otro producto o presentación ya tiene este código de barras",
                    )

            payload["product_id"] = product.require_id()
            plan.payload = payload
            if plan.ok and existing is not None:
                self.settle(
                    plan,
                    mode,
                    changed=any(
                        payload[name] != value for name, value in current.items()
                    ),
                )

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        for plan in self.writes(plans):
            with self.row(plan):
                if plan.target_id is None:
                    result = self.create.handle(
                        CreateProductPresentationCommand(**plan.payload)
                    )
                    plan.record_id = result["id"]
                else:
                    self.update.handle(
                        UpdateProductPresentationCommand(
                            presentation_id=plan.target_id, **plan.payload
                        )
                    )
                    plan.record_id = plan.target_id
