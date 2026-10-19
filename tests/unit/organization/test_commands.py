"""Unit tests for the organization command handlers."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.inventory.location.domain.entities import Location
from src.inventory.warehouse.domain.entities import Warehouse
from src.organization.app.commands.branch import (
    CreateBranchCommand,
    CreateBranchCommandHandler,
    DeleteBranchCommand,
    DeleteBranchCommandHandler,
    UpdateBranchCommand,
    UpdateBranchCommandHandler,
)
from src.organization.app.commands.emission_point import (
    UpdateEmissionPointCommand,
    UpdateEmissionPointCommandHandler,
)
from src.organization.app.commands.pos_terminal import (
    CreatePosTerminalCommand,
    CreatePosTerminalCommandHandler,
    TerminalPlacement,
    UpdatePosTerminalCommand,
    UpdatePosTerminalCommandHandler,
)
from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.organization.domain.exceptions import (
    EmissionPointOutsideBranchError,
    LocationOutsideBranchError,
    MainBranchDeletionError,
)
from src.shared.domain.exceptions import NotFoundError

# --- Helpers ---


def _branch(**overrides) -> Branch:
    defaults: dict[str, Any] = {"id": 1, "establishment_code": "001", "name": "Matriz"}
    defaults.update(overrides)
    return Branch(**defaults)


def _echo_repo(existing=None) -> Mock:
    """A repository that returns what it is given"""
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.create.side_effect = lambda entity: entity
    repo.update.side_effect = lambda entity: entity
    return repo


def _placement(
    point_branch: int = 1, warehouse_branch: int = 1, **missing: bool
) -> TerminalPlacement:
    """Branch 1 with emission point 10 and location 20 (in warehouse 30)"""
    branches = Mock()
    branches.get_by_id.return_value = None if missing.get("branch") else _branch()
    points = Mock()
    points.get_by_id.return_value = (
        None
        if missing.get("point")
        else EmissionPoint(id=10, branch_id=point_branch, code="001")
    )
    locations = Mock()
    locations.get_by_id.return_value = (
        None
        if missing.get("location")
        else Location(id=20, warehouse_id=30, name="General", code="GENERAL")
    )
    warehouses = Mock()
    warehouses.get_by_id.return_value = Warehouse(
        id=30, branch_id=warehouse_branch, name="Bodega", code="BOD-001"
    )
    return TerminalPlacement(branches, points, locations, warehouses)


def _create_terminal(placement: TerminalPlacement) -> dict:
    handler = CreatePosTerminalCommandHandler(_echo_repo(), placement)
    return handler.handle(
        CreatePosTerminalCommand(
            branch_id=1,
            emission_point_id=10,
            default_location_id=20,
            code="CAJA-01",
            name="Caja 1",
        )
    )


# --- Branches ---


def test_a_new_branch_is_never_the_main_one():
    repo = _echo_repo()

    result = CreateBranchCommandHandler(repo).handle(
        CreateBranchCommand(establishment_code="002", name="Guayaquil")
    )

    assert result["establishment_code"] == "002"
    assert result["is_main"] is False


def test_updating_a_branch_keeps_whether_it_is_the_main_one():
    repo = _echo_repo(existing=_branch(is_main=True))

    result = UpdateBranchCommandHandler(repo).handle(
        UpdateBranchCommand(branch_id=1, establishment_code="001", name="Quito")
    )

    assert (result["name"], result["is_main"]) == ("Quito", True)


def test_updating_a_missing_branch_raises():
    with pytest.raises(NotFoundError):
        UpdateBranchCommandHandler(_echo_repo()).handle(
            UpdateBranchCommand(branch_id=9, establishment_code="001", name="X")
        )


def test_the_main_branch_cant_be_deleted():
    repo = _echo_repo(existing=_branch(is_main=True))

    with pytest.raises(MainBranchDeletionError):
        DeleteBranchCommandHandler(repo).handle(DeleteBranchCommand(branch_id=1))
    repo.delete.assert_not_called()


def test_another_branch_is_deleted():
    repo = _echo_repo(existing=_branch(id=2, establishment_code="002"))

    DeleteBranchCommandHandler(repo).handle(DeleteBranchCommand(branch_id=2))

    repo.delete.assert_called_once_with(2)


# --- Emission points ---


def test_updating_an_emission_point_keeps_its_branch():
    repo = _echo_repo(existing=EmissionPoint(id=10, branch_id=4, code="001"))

    result = UpdateEmissionPointCommandHandler(repo).handle(
        UpdateEmissionPointCommand(emission_point_id=10, code="002", name="Caja")
    )

    assert (result["branch_id"], result["code"]) == (4, "002")


# --- Terminals ---


def test_a_terminal_issues_and_takes_stock_in_its_branch():
    result = _create_terminal(_placement())

    assert result["branch_id"] == 1
    assert result["emission_point_id"] == 10
    assert result["default_location_id"] == 20


def test_a_terminal_cant_issue_by_an_emission_point_of_another_branch():
    with pytest.raises(EmissionPointOutsideBranchError):
        _create_terminal(_placement(point_branch=2))


def test_a_terminal_cant_take_stock_from_a_location_of_another_branch():
    with pytest.raises(LocationOutsideBranchError):
        _create_terminal(_placement(warehouse_branch=2))


@pytest.mark.parametrize("missing", ["branch", "point", "location"])
def test_a_terminal_needs_its_branch_emission_point_and_location(missing):
    with pytest.raises(NotFoundError):
        _create_terminal(_placement(**{missing: True}))


def test_updating_a_terminal_checks_against_its_own_branch():
    existing = PosTerminal(
        id=5,
        branch_id=1,
        emission_point_id=10,
        default_location_id=20,
        code="CAJA-01",
        name="Caja 1",
    )
    handler = UpdatePosTerminalCommandHandler(
        _echo_repo(existing=existing), _placement(warehouse_branch=2)
    )

    with pytest.raises(LocationOutsideBranchError):
        handler.handle(
            UpdatePosTerminalCommand(
                terminal_id=5,
                emission_point_id=10,
                default_location_id=20,
                code="CAJA-01",
                name="Caja 1",
            )
        )
