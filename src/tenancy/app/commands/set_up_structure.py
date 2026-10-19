from dataclasses import dataclass

from wireup import injectable

from src.inventory.location.app.repositories import LocationRepository
from src.inventory.location.domain.entities import Location
from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.inventory.warehouse.domain.entities import Warehouse
from src.organization.app.repositories import (
    BranchRepository,
    EmissionPointRepository,
    PosTerminalRepository,
)
from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.shared.app.commands import Command, CommandHandler

MAIN_ESTABLISHMENT = "001"
MAIN_EMISSION_POINT = "001"
MAIN_WAREHOUSE = "BOD-001"
MAIN_LOCATION = "GENERAL"
MAIN_TERMINAL = "CAJA-01"


@dataclass
class SetUpTenantStructureCommand(Command):
    branch_address: str | None = None


@injectable(lifetime="scoped")
class SetUpTenantStructureCommandHandler(
    CommandHandler[SetUpTenantStructureCommand, dict]
):
    """Deja operativa una empresa nueva: la matriz (establecimiento 001), su
    punto de emisión 001, una bodega con su ubicación por defecto y una
    terminal. Corre en el contexto de la empresa.

    Idempotente: una empresa que ya tiene sucursales queda como está."""

    def __init__(
        self,
        branches: BranchRepository,
        emission_points: EmissionPointRepository,
        warehouses: WarehouseRepository,
        locations: LocationRepository,
        terminals: PosTerminalRepository,
    ):
        self.branches = branches
        self.emission_points = emission_points
        self.warehouses = warehouses
        self.locations = locations
        self.terminals = terminals

    def _handle(self, command: SetUpTenantStructureCommand) -> dict:
        if self.branches.count_by() > 0:
            return {"structure_created": False}

        branch = self.branches.create(
            Branch(
                establishment_code=MAIN_ESTABLISHMENT,
                name="Matriz",
                address=command.branch_address,
                is_main=True,
            )
        )
        point = self.emission_points.create(
            EmissionPoint(
                branch_id=branch.require_id(),
                code=MAIN_EMISSION_POINT,
                name="Punto de emisión 001",
            )
        )
        warehouse = self.warehouses.create(
            Warehouse(
                branch_id=branch.require_id(),
                name="Bodega principal",
                code=MAIN_WAREHOUSE,
                address=command.branch_address,
                is_default=True,
            )
        )
        location = self.locations.create(
            Location(
                warehouse_id=warehouse.require_id(),
                name="General",
                code=MAIN_LOCATION,
            )
        )
        terminal = self.terminals.create(
            PosTerminal(
                branch_id=branch.require_id(),
                emission_point_id=point.require_id(),
                default_location_id=location.require_id(),
                code=MAIN_TERMINAL,
                name="Caja 1",
            )
        )
        return {
            "structure_created": True,
            "branch_id": branch.require_id(),
            "emission_point_id": point.require_id(),
            "warehouse_id": warehouse.require_id(),
            "location_id": location.require_id(),
            "terminal_id": terminal.require_id(),
        }
