"""The minimal structure of a new tenant (S2.5)"""

from unittest.mock import Mock

from src.tenancy.app.commands.set_up_structure import (
    SetUpTenantStructureCommand,
    SetUpTenantStructureCommandHandler,
)


def _repo(start_id: int) -> Mock:
    """A repository that gives each created entity an id"""
    repo = Mock()
    repo.count_by.return_value = 0

    def create(entity):
        entity.id = start_id
        return entity

    repo.create.side_effect = create
    return repo


def _handler(existing_branches: int = 0, default_list: bool = True):
    repos = [_repo(start_id) for start_id in (1, 2, 3, 4, 5, 6)]
    repos[0].count_by.return_value = existing_branches
    if not default_list:
        repos[5].default.return_value = None
    return SetUpTenantStructureCommandHandler(*repos), repos


def test_a_new_tenant_gets_its_main_branch_emission_point_warehouse_and_terminal():
    handler, (branches, points, warehouses, locations, terminals, lists) = _handler(
        default_list=False
    )

    result = handler.handle(SetUpTenantStructureCommand(branch_address="Av. Quito"))

    [branch] = branches.create.call_args.args
    [point] = points.create.call_args.args
    [warehouse] = warehouses.create.call_args.args
    [location] = locations.create.call_args.args
    [terminal] = terminals.create.call_args.args
    assert (branch.establishment_code, branch.is_main) == ("001", True)
    assert branch.address == "Av. Quito"
    assert (point.branch_id, point.code) == (1, "001")
    assert (warehouse.branch_id, warehouse.is_default) == (1, True)
    assert location.warehouse_id == 3
    assert (terminal.branch_id, terminal.emission_point_id) == (1, 2)
    assert terminal.default_location_id == 4
    assert result["structure_created"] is True
    assert result["terminal_id"] == 5
    [general] = lists.create.call_args.args
    assert (general.name, general.is_default) == ("General", True)


def test_a_tenant_with_branches_is_left_as_it_is():
    handler, repos = _handler(existing_branches=1)

    result = handler.handle(SetUpTenantStructureCommand())

    assert result == {"structure_created": False}
    for repo in repos:
        repo.create.assert_not_called()


def test_a_tenant_without_its_general_price_list_gets_it():
    handler, repos = _handler(existing_branches=1, default_list=False)

    result = handler.handle(SetUpTenantStructureCommand())

    assert result == {"structure_created": False}
    [general] = repos[5].create.call_args.args
    assert general.is_default
    for repo in repos[:5]:
        repo.create.assert_not_called()
