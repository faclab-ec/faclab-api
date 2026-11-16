"""Saldos iniciales de inventario (S5.8): la cantidad de un producto en una
ubicación, con su costo.

Entran como ajustes auditados (`initial_balance`), no como escritura directa del
stock: un ajuste por bodega y por lote, que lleva cada ubicación a la cantidad
del archivo. Lo que agrega entra al costo de la fila (por unidad base) y fija el
costo promedio de la ubicación (S5.6); sin costo, al promedio que tenga o al
precio de compra del producto. Repetir el archivo no mueve nada: la diferencia
ya es cero.
"""

from collections import defaultdict
from decimal import Decimal

from wireup import injectable

from src.imports.app.columns import Column, money, quantity, text
from src.imports.app.kinds.base import NOT_ALLOWED, NOT_FOUND, KindImporter, RowPlan
from src.imports.app.lookups import ImportLookups, key
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRowAction,
)
from src.inventory.adjustment.app.commands.adjustment import (
    AddAdjustmentItemCommand,
    AddAdjustmentItemCommandHandler,
    ConfirmAdjustmentCommand,
    ConfirmAdjustmentCommandHandler,
    CreateAdjustmentCommand,
    CreateAdjustmentCommandHandler,
)
from src.inventory.adjustment.domain.entities import AdjustmentReason

WAREHOUSE = Column(
    "bodega",
    "warehouse",
    "Código de la bodega (debe existir)",
    "BOD-001",
    key=True,
    required=True,
    parse=text(32),
)
LOCATION = Column(
    "ubicacion",
    "location",
    "Código de la ubicación dentro de la bodega (debe existir)",
    "GENERAL",
    key=True,
    required=True,
    parse=text(32),
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
QUANTITY = Column(
    "cantidad",
    "quantity",
    "Cantidad que hay, en unidad base: el stock de la ubicación queda en ella",
    "1500",
    required=True,
    parse=quantity,
)
UNIT_COST = Column(
    "costo_unitario",
    "unit_cost",
    "Costo por unidad base, sin IVA, de lo que entra; vacía: el promedio de la "
    "ubicación o el precio de compra del producto",
    "0.08",
    parse=money,
)


@injectable(lifetime="scoped")
class StockImporter(KindImporter):
    kind = ImportKind.STOCK
    columns = (WAREHOUSE, LOCATION, SKU, QUANTITY, UNIT_COST)

    def __init__(
        self,
        lookups: ImportLookups,
        create: CreateAdjustmentCommandHandler,
        add_item: AddAdjustmentItemCommandHandler,
        confirm: ConfirmAdjustmentCommandHandler,
    ):
        self.lookups = lookups
        self.create = create
        self.add_item = add_item
        self.confirm = confirm

    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        warehouses = self.lookups.warehouses()
        locations = self.lookups.locations(ref.id for ref in warehouses.values())
        products = self.lookups.products(plan.get(SKU) for plan in plans)
        units = {unit.id: unit for unit in self.lookups.units().values()}

        resolved: list[RowPlan] = []
        for plan in plans:
            warehouse = warehouses.get(key(plan.get(WAREHOUSE)))
            location = (
                locations.get((warehouse.id, key(plan.get(LOCATION))))
                if warehouse
                else None
            )
            product = products.get(plan.get(SKU))
            if warehouse is None:
                plan.error(
                    WAREHOUSE, NOT_FOUND, f"No existe la bodega {plan.get(WAREHOUSE)}"
                )
            elif location is None:
                plan.error(
                    LOCATION,
                    NOT_FOUND,
                    f"La bodega {warehouse.code} no tiene la ubicación "
                    f"{plan.get(LOCATION)}",
                )
            if product is None:
                plan.error(
                    SKU, NOT_FOUND, f"No existe un producto con SKU {plan.get(SKU)}"
                )
            elif product.is_service:
                plan.error(SKU, NOT_ALLOWED, "Es un servicio: no lleva stock")
            if not self.require(plan, QUANTITY):
                continue
            if warehouse is None or location is None or product is None:
                continue
            unit = units.get(product.unit_of_measure_id or 0)
            if unit is not None:
                self.fits_decimals(
                    plan, QUANTITY, plan.get(QUANTITY), unit.decimals, unit.symbol
                )
            plan.payload = {
                "warehouse_id": warehouse.id,
                "location_id": location.id,
                "product_id": product.require_id(),
                "quantity": plan.get(QUANTITY),
                "unit_cost": plan.get(UNIT_COST),
            }
            resolved.append(plan)

        self.unique_in_file(
            resolved,
            lambda p: (p.payload["location_id"], p.payload["product_id"]),
            None,
            "El producto en esa ubicación",
        )
        resolved = [plan for plan in resolved if plan.ok]
        stock = self.lookups.stock(
            (p.payload["product_id"], p.payload["location_id"]) for p in resolved
        )
        for plan in resolved:
            current = stock.get(
                (plan.payload["product_id"], plan.payload["location_id"]), Decimal(0)
            )
            if plan.payload["quantity"] == current:
                plan.action = ImportRowAction.UNCHANGED
            elif current == 0:
                plan.action = ImportRowAction.CREATE
            else:
                self.settle(plan, mode, changed=True)

    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        by_warehouse: dict[int, list[RowPlan]] = defaultdict(list)
        for plan in self.writes(plans):
            by_warehouse[plan.payload["warehouse_id"]].append(plan)

        for warehouse_id, lines in sorted(by_warehouse.items()):
            with self.row(None):
                adjustment = self.create.handle(
                    CreateAdjustmentCommand(
                        warehouse_id=warehouse_id,
                        reason=AdjustmentReason.INITIAL_BALANCE.value,
                        notes=f"Importación #{job.id}",
                        adjusted_by=job.user_name,
                    )
                )
            for plan in lines:
                with self.row(plan):
                    self.add_item.handle(
                        AddAdjustmentItemCommand(
                            adjustment_id=adjustment["id"],
                            product_id=plan.payload["product_id"],
                            location_id=plan.payload["location_id"],
                            actual_quantity=plan.payload["quantity"],
                            unit_cost=plan.payload["unit_cost"],
                        )
                    )
                plan.record_id = adjustment["id"]
            with self.row(None, f"Ajuste de la bodega {warehouse_id}"):
                self.confirm.handle(ConfirmAdjustmentCommand(id=adjustment["id"]))
