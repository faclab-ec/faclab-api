"""Precios de las listas (S5.8): el de una presentación de un producto en una
lista, desde una cantidad. La lista debe existir; la general solo guarda
escalas (cantidad mínima mayor que cero)."""

from decimal import Decimal

from wireup import injectable

from src.imports.app.columns import Column, money, quantity, text
from src.imports.app.kinds.base import NOT_ALLOWED, NOT_FOUND, KindImporter, RowPlan
from src.imports.app.lookups import ImportLookups, PresentationRef, key
from src.imports.domain.entities import ImportJob, ImportKind, ImportMode
from src.pricing.app.commands.items import (
    CreatePriceListItemCommand,
    CreatePriceListItemCommandHandler,
    UpdatePriceListItemCommand,
    UpdatePriceListItemCommandHandler,
)
from src.shared.domain.quantity import presentation_decimals

PRICE_LIST = Column(
    "lista",
    "price_list",
    "Nombre de la lista de precios (debe existir)",
    "Mayorista",
    key=True,
    required=True,
    parse=text(64),
)
SKU = Column(
    "sku",
    "sku",
    "SKU del producto (debe existir)",
    "TOR-0001",
    key=True,
    required=True,
    parse=text(64),
)
PRESENTATION = Column(
    "presentacion",
    "presentation",
    "Nombre de la presentación; vacía: la unidad base",
    "Caja x100",
    key=True,
    parse=text(64),
)
MIN_QUANTITY = Column(
    "cantidad_minima",
    "min_quantity",
    "Desde qué cantidad (en la presentación) aplica; vacía: 0, el precio base "
    "de la lista. En la lista general, mayor que cero",
    "10",
    key=True,
    parse=quantity,
)
PRICE = Column(
    "precio",
    "price",
    "Precio de la presentación sin IVA",
    "12.90",
    required=True,
    parse=money,
)


@injectable(lifetime="scoped")
class PriceImporter(KindImporter):
    kind = ImportKind.PRICES
    columns = (PRICE_LIST, SKU, PRESENTATION, MIN_QUANTITY, PRICE)

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreatePriceListItemCommandHandler,
        update: UpdatePriceListItemCommandHandler,
    ):
        self.lookups = lookups
        self.create = create
        self.update = update

    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        lists = self.lookups.price_lists()
        products = self.lookups.products(plan.get(SKU) for plan in plans)
        presentations = self.lookups.presentations(
            product.require_id() for product in products.values()
        )
        units = {unit.id: unit for unit in self.lookups.units().values()}
        items = self.lookups.price_items(
            (price_list.id for price_list in lists.values()),
            (product.require_id() for product in products.values()),
        )

        resolved: list[RowPlan] = []
        for plan in plans:
            price_list = lists.get(key(plan.get(PRICE_LIST)))
            if price_list is None:
                plan.error(
                    PRICE_LIST,
                    NOT_FOUND,
                    f"No existe la lista de precios {plan.get(PRICE_LIST)}",
                )
            product = products.get(plan.get(SKU))
            if product is None:
                plan.error(
                    SKU, NOT_FOUND, f"No existe un producto con SKU {plan.get(SKU)}"
                )
            if price_list is None or product is None:
                continue
            presentation = self._presentation(
                plan, presentations.get(product.require_id(), [])
            )
            if presentation is None:
                continue
            min_quantity = plan.get(MIN_QUANTITY, Decimal(0))
            if price_list.is_default and min_quantity <= 0:
                plan.error(
                    MIN_QUANTITY,
                    NOT_ALLOWED,
                    "La lista general solo guarda escalas: su precio base es el del "
                    "producto. Escriba una cantidad mínima mayor que cero",
                )
            unit = units.get(product.unit_of_measure_id or 0)
            if unit is not None:
                self.fits_decimals(
                    plan,
                    MIN_QUANTITY,
                    min_quantity,
                    presentation_decimals(unit.decimals, presentation.factor),
                    unit.symbol,
                )
            plan.payload = {
                "price_list_id": price_list.id,
                "product_id": product.require_id(),
                "presentation_id": presentation.id,
                "min_quantity": min_quantity,
            }
            resolved.append(plan)

        self.unique_in_file(
            resolved,
            lambda p: (
                p.payload["price_list_id"],
                p.payload["presentation_id"],
                p.payload["min_quantity"],
            ),
            None,
            "El precio de esa lista, presentación y cantidad",
        )
        for plan in resolved:
            if not plan.ok:
                continue
            existing = items.get(
                (
                    plan.payload["price_list_id"],
                    plan.payload["presentation_id"],
                    plan.payload["min_quantity"],
                )
            )
            if existing is None:
                if self.require(plan, PRICE):
                    plan.payload["price"] = plan.get(PRICE)
                continue
            plan.target_id = existing.id
            plan.payload["price"] = plan.get(PRICE, existing.price)
            self.settle(plan, mode, changed=plan.payload["price"] != existing.price)

    def _presentation(
        self, plan: RowPlan, presentations: list[PresentationRef]
    ) -> PresentationRef | None:
        if not plan.has(PRESENTATION):
            found = next((p for p in presentations if p.is_base), None)
        else:
            found = next(
                (
                    p
                    for p in presentations
                    if key(p.name) == key(plan.get(PRESENTATION))
                ),
                None,
            )
        if found is None:
            plan.error(
                PRESENTATION,
                NOT_FOUND,
                f"El producto no tiene la presentación {plan.get(PRESENTATION)}",
            )
        elif not found.is_active:
            plan.error(PRESENTATION, NOT_ALLOWED, "La presentación está inactiva")
        return found if plan.ok else None

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        for plan in self.writes(plans):
            with self.row(plan):
                payload = plan.payload
                if plan.target_id is None:
                    result = self.create.handle(CreatePriceListItemCommand(**payload))
                    plan.record_id = result["id"]
                else:
                    self.update.handle(
                        UpdatePriceListItemCommand(
                            price_list_id=payload["price_list_id"],
                            item_id=plan.target_id,
                            price=payload["price"],
                            min_quantity=payload["min_quantity"],
                        )
                    )
                    plan.record_id = plan.target_id
