from dataclasses import dataclass

from wireup import injectable

from src.inventory.location.app.repositories import LocationRepository
from src.inventory.warehouse.app.repositories import WarehouseRepository
from src.organization.app.repositories import (
    BranchRepository,
    EmissionPointRepository,
    PosTerminalRepository,
)
from src.organization.domain.entities import PosTerminal
from src.organization.domain.exceptions import (
    EmissionPointOutsideBranchError,
    LocationOutsideBranchError,
)
from src.shared.app.audit import AuditAction, AuditTrail, changed, snapshot
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.exceptions import NotFoundError

AUDITED_FIELDS = (
    "code",
    "name",
    "emission_point_id",
    "default_location_id",
    "is_active",
)


@injectable(lifetime="scoped")
class TerminalPlacement:
    """Checks that a terminal's emission point and default location are of its
    branch. The location's branch is that of its warehouse."""

    def __init__(
        self,
        branches: BranchRepository,
        emission_points: EmissionPointRepository,
        locations: LocationRepository,
        warehouses: WarehouseRepository,
    ):
        self.branches = branches
        self.emission_points = emission_points
        self.locations = locations
        self.warehouses = warehouses

    def check(
        self, branch_id: int, emission_point_id: int, default_location_id: int
    ) -> None:
        if self.branches.get_by_id(branch_id) is None:
            raise NotFoundError(f"Branch {branch_id} not found")
        point = self.emission_points.get_by_id(emission_point_id)
        if point is None:
            raise NotFoundError(f"Emission point {emission_point_id} not found")
        if point.branch_id != branch_id:
            raise EmissionPointOutsideBranchError()
        location = self.locations.get_by_id(default_location_id)
        if location is None:
            raise NotFoundError(f"Location {default_location_id} not found")
        warehouse = self.warehouses.get_by_id(location.warehouse_id)
        if warehouse is None or warehouse.branch_id != branch_id:
            raise LocationOutsideBranchError()


@dataclass
class CreatePosTerminalCommand(Command):
    branch_id: int
    emission_point_id: int
    default_location_id: int
    code: str
    name: str
    is_active: bool = True


@injectable(lifetime="scoped")
class CreatePosTerminalCommandHandler(CommandHandler[CreatePosTerminalCommand, dict]):
    def __init__(
        self,
        repo: PosTerminalRepository,
        placement: TerminalPlacement,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.placement = placement
        self.audit = audit

    def _handle(self, command: CreatePosTerminalCommand) -> dict:
        self.placement.check(
            command.branch_id, command.emission_point_id, command.default_location_id
        )
        terminal = PosTerminal(
            branch_id=command.branch_id,
            emission_point_id=command.emission_point_id,
            default_location_id=command.default_location_id,
            code=command.code,
            name=command.name,
            is_active=command.is_active,
        )
        terminal = self.repo.create(terminal)
        self.audit.record(
            AuditAction.POS_TERMINAL_CREATED,
            terminal.require_id(),
            after=snapshot(terminal, *AUDITED_FIELDS),
            branch_id=terminal.branch_id,
        )
        return terminal.dict()


@dataclass
class UpdatePosTerminalCommand(Command):
    """The branch of a terminal is fixed when it is created"""

    terminal_id: int
    emission_point_id: int
    default_location_id: int
    code: str
    name: str
    is_active: bool = True


@injectable(lifetime="scoped")
class UpdatePosTerminalCommandHandler(CommandHandler[UpdatePosTerminalCommand, dict]):
    def __init__(
        self,
        repo: PosTerminalRepository,
        placement: TerminalPlacement,
        audit: AuditTrail,
    ):
        self.repo = repo
        self.placement = placement
        self.audit = audit

    def _handle(self, command: UpdatePosTerminalCommand) -> dict:
        terminal = self.repo.get_by_id(command.terminal_id)
        if terminal is None:
            raise NotFoundError(f"POS terminal {command.terminal_id} not found")
        previous = snapshot(terminal, *AUDITED_FIELDS)
        self.placement.check(
            terminal.branch_id, command.emission_point_id, command.default_location_id
        )
        terminal = PosTerminal(
            id=command.terminal_id,
            branch_id=terminal.branch_id,
            emission_point_id=command.emission_point_id,
            default_location_id=command.default_location_id,
            code=command.code,
            name=command.name,
            is_active=command.is_active,
        )
        terminal = self.repo.update(terminal)
        before, after = changed(previous, snapshot(terminal, *AUDITED_FIELDS))
        if after:
            self.audit.record(
                AuditAction.POS_TERMINAL_UPDATED,
                command.terminal_id,
                before=before,
                after=after,
                branch_id=terminal.branch_id,
            )
        return terminal.dict()


@dataclass
class DeletePosTerminalCommand(Command):
    terminal_id: int


@injectable(lifetime="scoped")
class DeletePosTerminalCommandHandler(CommandHandler[DeletePosTerminalCommand, None]):
    def __init__(self, repo: PosTerminalRepository, audit: AuditTrail):
        self.repo = repo
        self.audit = audit

    def _handle(self, command: DeletePosTerminalCommand) -> None:
        terminal = self.repo.get_by_id(command.terminal_id)
        if terminal is None:
            raise NotFoundError(f"POS terminal {command.terminal_id} not found")
        self.repo.delete(command.terminal_id)
        self.audit.record(
            AuditAction.POS_TERMINAL_DELETED,
            command.terminal_id,
            before=snapshot(terminal, *AUDITED_FIELDS),
            branch_id=terminal.branch_id,
        )
