"""Productos (S5.8): uno por SKU, con su unidad base, precios, IVA y el código de
barras de su presentación base. Una categoría que no existe se crea."""

from decimal import Decimal
from typing import Any

from wireup import injectable

from src.catalog.product.app.commands.create_category import (
    CreateCategoryCommand,
    CreateCategoryCommandHandler,
)
from src.catalog.product.app.commands.create_product import (
    CreateProductCommand,
    CreateProductCommandHandler,
)
from src.catalog.product.app.commands.update_product import (
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.domain.entities import Product
from src.imports.app.columns import (
    Column,
    boolean,
    choice,
    money,
    quantity,
    text,
    whole,
)
from src.imports.app.kinds.base import (
    ALREADY_IN_USE,
    NOT_ALLOWED,
    NOT_FOUND,
    KindImporter,
    RowPlan,
)
from src.imports.app.lookups import ImportLookups, key
from src.imports.domain.entities import ImportJob, ImportKind, ImportMode
from src.shared.domain.tax import (
    CONSTRUCTION_MATERIAL_TAX_CODE,
    ConstructionMaterialCode,
    TaxCode,
)

# El IVA por su tarifa, como lo escribe una ferretería, o por su código
TAX_OPTIONS: dict[str, TaxCode] = {
    **{code.value: code for code in TaxCode},
    "15": TaxCode.VAT_15,
    "15%": TaxCode.VAT_15,
    "5": TaxCode.VAT_5,
    "5%": TaxCode.VAT_5,
    "0": TaxCode.VAT_0,
    "0%": TaxCode.VAT_0,
    "exento": TaxCode.EXEMPT,
    "no_objeto": TaxCode.NOT_TAXED,
}

SKU = Column(
    "sku",
    "sku",
    "Código interno del producto, único en la empresa",
    "TOR-0001",
    key=True,
    required=True,
    parse=text(64),
)
NAME = Column(
    "nombre",
    "name",
    "Nombre del producto",
    "Tornillo 1/2",
    required=True,
    parse=text(128),
)
DESCRIPTION = Column("descripcion", "description", "Descripción", "", parse=text(255))
CATEGORY = Column(
    "categoria",
    "category",
    "Nombre de la categoría; si no existe, se crea",
    "Tornillería",
    parse=text(64),
)
UNIT = Column(
    "unidad",
    "unit",
    "Símbolo de la unidad base, en la que se lleva el stock (debe existir)",
    "und",
    required=True,
    parse=text(16),
)
BARCODE = Column(
    "codigo_barras",
    "barcode",
    "Código de barras de la unidad base, único en la empresa",
    "7861234500011",
    parse=text(64),
)
PURCHASE_PRICE = Column(
    "precio_compra",
    "purchase_price",
    "Costo por unidad base, sin IVA",
    "0.08",
    parse=money,
)
SALE_PRICE = Column(
    "precio_venta",
    "sale_price",
    "Precio de venta por unidad base, sin IVA",
    "0.15",
    required=True,
    parse=money,
)
TAX = Column(
    "iva",
    "tax_code",
    "Tarifa de IVA: 15, 5, 0, EXENTO, NO_OBJETO o el código (VAT_15); vacía al "
    "crear, 15",
    "15",
    parse=choice(TAX_OPTIONS, "IVA"),
)
MATERIAL = Column(
    "material_construccion",
    "construction_material_code",
    "Código de material de construcción del SRI (Tabla 31, p. ej. F010401 "
    "cemento); exige IVA 5",
    "",
    parse=choice({code.value: code for code in ConstructionMaterialCode}, "Código"),
)
MIN_STOCK = Column(
    "stock_minimo", "min_stock", "Stock mínimo, en unidad base", "10", parse=quantity
)
MAX_STOCK = Column(
    "stock_maximo", "max_stock", "Stock máximo, en unidad base", "", parse=quantity
)
REORDER_POINT = Column(
    "punto_reorden",
    "reorder_point",
    "Punto de reorden, en unidad base",
    "20",
    parse=quantity,
)
LEAD_TIME = Column(
    "dias_reposicion",
    "lead_time_days",
    "Días que tarda en reponerse",
    "",
    parse=whole,
)
IS_SERVICE = Column(
    "es_servicio",
    "is_service",
    "SI si es un servicio (no lleva stock); vacía al crear, NO",
    "NO",
    parse=boolean,
)
IS_ACTIVE = Column(
    "activo",
    "is_active",
    "NO para dejarlo inactivo; vacía al crear, SI",
    "SI",
    parse=boolean,
)

# Campos del producto que la plantilla llena directamente
_FIELDS = (
    NAME,
    DESCRIPTION,
    PURCHASE_PRICE,
    SALE_PRICE,
    TAX,
    MATERIAL,
    MIN_STOCK,
    MAX_STOCK,
    REORDER_POINT,
    LEAD_TIME,
    IS_SERVICE,
    IS_ACTIVE,
)
_DEFAULTS: dict[str, Any] = {
    "description": None,
    "purchase_price": None,
    "sale_price": None,
    "tax_code": TaxCode.VAT_15,
    "construction_material_code": None,
    "min_stock": Decimal(0),
    "max_stock": None,
    "reorder_point": Decimal(0),
    "lead_time_days": None,
    "is_service": False,
    "is_active": True,
}


def _current(product: Product, barcode: str | None) -> dict[str, Any]:
    return {
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category_id": product.category_id,
        "unit_of_measure_id": product.unit_of_measure_id,
        "purchase_price": product.purchase_price,
        "sale_price": product.sale_price,
        "tax_code": product.tax_code,
        "construction_material_code": product.construction_material_code,
        "min_stock": product.min_stock,
        "max_stock": product.max_stock,
        "reorder_point": product.reorder_point,
        "lead_time_days": product.lead_time_days,
        "is_service": product.is_service,
        "is_active": product.is_active,
        "barcode": barcode,
    }


@injectable(lifetime="scoped")
class ProductImporter(KindImporter):
    kind = ImportKind.PRODUCTS
    columns = (
        SKU,
        NAME,
        DESCRIPTION,
        CATEGORY,
        UNIT,
        BARCODE,
        PURCHASE_PRICE,
        SALE_PRICE,
        TAX,
        MATERIAL,
        MIN_STOCK,
        MAX_STOCK,
        REORDER_POINT,
        LEAD_TIME,
        IS_SERVICE,
        IS_ACTIVE,
    )

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreateProductCommandHandler,
        update: UpdateProductCommandHandler,
        create_category: CreateCategoryCommandHandler,
    ):
        self.lookups = lookups
        self.create = create
        self.update = update
        self.create_category = create_category

    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        self.unique_in_file(plans, lambda p: p.get(SKU), SKU, "El SKU")
        self.unique_in_file(plans, lambda p: p.get(BARCODE), BARCODE, "El código")
        plans = [plan for plan in plans if plan.ok]
        products = self.lookups.products(plan.get(SKU) for plan in plans)
        units = self.lookups.units()
        units_by_id = {unit.id: unit for unit in units.values()}
        categories = self.lookups.categories()
        owners = self.lookups.barcodes(
            plan.get(BARCODE) for plan in plans if plan.has(BARCODE)
        )
        bases = {
            product_id: next((p.barcode for p in presentations if p.is_base), None)
            for product_id, presentations in self.lookups.presentations(
                product.require_id() for product in products.values()
            ).items()
        }

        for plan in plans:
            existing = products.get(plan.get(SKU))
            if existing is not None:
                plan.target_id = existing.require_id()
                if mode == ImportMode.SKIP:
                    self.settle(plan, mode, changed=False)
                    continue
                current = _current(existing, bases.get(plan.target_id))
            elif not self.require(plan, NAME, UNIT, SALE_PRICE):
                continue
            else:
                current = {"sku": plan.get(SKU), "category_id": None, "barcode": None}
                current |= _DEFAULTS

            payload = dict(current)
            for column in _FIELDS:
                if plan.has(column):
                    payload[column.field] = plan.get(column)

            if plan.has(UNIT):
                unit = units.get(key(plan.get(UNIT)))
                if unit is None:
                    plan.error(UNIT, NOT_FOUND, f"No existe la unidad {plan.get(UNIT)}")
                    continue
                payload["unit_of_measure_id"] = unit.id
            else:
                unit = units_by_id.get(payload["unit_of_measure_id"])

            if plan.has(CATEGORY):
                category_id = categories.get(key(plan.get(CATEGORY)))
                payload["category_id"] = category_id
                if category_id is None:
                    payload["new_category"] = plan.get(CATEGORY)

            if plan.has(BARCODE):
                owner = owners.get(plan.get(BARCODE))
                if owner is not None and not (
                    owner.is_base and owner.product_id == plan.target_id
                ):
                    plan.error(
                        BARCODE,
                        ALREADY_IN_USE,
                        "Otro producto o presentación ya tiene este código de barras",
                    )
                payload["barcode"] = plan.get(BARCODE)

            if (
                payload["construction_material_code"] is not None
                and payload["tax_code"] != CONSTRUCTION_MATERIAL_TAX_CODE
            ):
                plan.error(
                    MATERIAL if plan.has(MATERIAL) else TAX,
                    NOT_ALLOWED,
                    "Un material de construcción lleva IVA 5",
                )

            if unit is not None:
                for column in (MIN_STOCK, MAX_STOCK, REORDER_POINT):
                    self.fits_decimals(
                        plan, column, payload[column.field], unit.decimals, unit.symbol
                    )

            plan.payload = payload
            if plan.ok and existing is not None:
                self.settle(
                    plan,
                    mode,
                    changed="new_category" in payload
                    or any(payload[name] != value for name, value in current.items()),
                )

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        created_categories: dict[str, int] = {}
        for plan in self.writes(plans):
            with self.row(plan):
                payload = dict(plan.payload)
                new_category = payload.pop("new_category", None)
                if new_category is not None:
                    payload["category_id"] = self._category(
                        new_category, created_categories
                    )
                payload.pop("sku")
                if plan.target_id is None:
                    result = self.create.handle(
                        CreateProductCommand(sku=plan.get(SKU), **payload)
                    )
                    plan.record_id = result["id"]
                else:
                    self.update.handle(
                        UpdateProductCommand(
                            product_id=plan.target_id, sku=plan.get(SKU), **payload
                        )
                    )
                    plan.record_id = plan.target_id

    def _category(self, name: str, created: dict[str, int]) -> int:
        """Una categoría nueva, una sola vez por nombre en el lote"""
        if key(name) not in created:
            category = self.create_category.handle(CreateCategoryCommand(name=name))
            created[key(name)] = category["id"]
        return created[key(name)]
