"""What the handlers of the catalog record, where it depends on the command.
Every action is driven through the API on PostgreSQL in
`tests/integration/postgres/test_audit_log.py`."""

from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from src.auth.app.commands.create_user import (
    CreateUserCommand,
    CreateUserCommandHandler,
)
from src.auth.app.commands.update_user_role import (
    UpdateUserRoleCommand,
    UpdateUserRoleCommandHandler,
)
from src.auth.domain.entities import Role, User
from src.catalog.product.app.commands.update_product import (
    UpdateProductCommand,
    UpdateProductCommandHandler,
)
from src.catalog.product.domain.entities import Product
from src.inventory.movement.app.commands.movement import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.organization.app.commands.branch import (
    DeleteBranchCommand,
    DeleteBranchCommandHandler,
    UpdateBranchCommand,
    UpdateBranchCommandHandler,
)
from src.organization.domain.entities import Branch
from src.shared.app.audit import AuditAction
from src.tenancy.domain.entities import Membership
from tests.audit import FakeAuditTrail

TENANT = UUID("00000000-0000-4000-8000-00000000000a")


def _echo(existing=None) -> Mock:
    repo = Mock()
    repo.get_by_id.return_value = existing
    repo.create.side_effect = lambda entity: replace(entity, id=entity.id or 1)
    repo.update.side_effect = lambda entity: entity
    return repo


# Products


def _product(**overrides: Any) -> Product:
    defaults: dict[str, Any] = {
        "id": 1,
        "sku": "TAL-001",
        "name": "Taladro",
        "purchase_price": Decimal("40"),
        "sale_price": Decimal("50"),
    }
    return Product(**{**defaults, **overrides})


def _update_product(**changes: Any) -> FakeAuditTrail:
    audit = FakeAuditTrail()
    existing = _product()
    command = UpdateProductCommand(
        product_id=1,
        sku=existing.sku,
        name=existing.name,
        purchase_price=existing.purchase_price,
        sale_price=existing.sale_price,
    )
    UpdateProductCommandHandler(_echo(existing), MagicMock(), audit).handle(
        replace(command, **changes)
    )
    return audit


def test_a_new_price_is_a_price_change_with_only_what_changed():
    audit = _update_product(sale_price=Decimal("55"), name="Taladro 600W")

    (entry,) = audit.entries
    assert entry.action == AuditAction.PRODUCT_PRICE_CHANGED
    assert entry.before == {"name": "Taladro", "sale_price": Decimal("50")}
    assert entry.after == {"name": "Taladro 600W", "sale_price": Decimal("55")}


def test_another_change_is_an_update():
    audit = _update_product(name="Taladro 600W")

    assert audit.actions == [AuditAction.PRODUCT_UPDATED]


def test_a_put_that_changes_nothing_leaves_no_entry():
    assert _update_product().entries == []


# Movements


@pytest.mark.parametrize(("manual", "entries"), [(True, 1), (False, 0)])
def test_only_the_manual_movement_is_audited(manual, entries):
    audit = FakeAuditTrail()
    handler = CreateMovementCommandHandler(_echo(), MagicMock(), Mock(), audit)

    handler.handle(
        CreateMovementCommand(
            product_id=3, quantity=5, type="IN", location_id=2, manual=manual
        )
    )

    assert len(audit.entries) == entries


# Users


def _create_user(audit: FakeAuditTrail) -> None:
    users = Mock()
    users.get_by_username.return_value = None
    users.get_by_email.return_value = None
    users.create.side_effect = lambda user: replace(user, id=5)
    memberships = Mock()
    memberships.create.side_effect = lambda membership: membership
    hasher = Mock()
    hasher.hash.return_value = "hash"
    CreateUserCommandHandler(users, memberships, hasher, MagicMock(), audit).handle(
        CreateUserCommand(
            tenant_id=TENANT,
            username="ana",
            email="ana@example.com",
            password="Secreta-123",
            role=Role.CASHIER.value,
            full_name="Ana Pérez",
        )
    )


def test_a_new_user_is_audited_without_email_nor_password(in_tenant):
    audit = FakeAuditTrail()

    _create_user(audit)

    (entry,) = audit.entries
    assert (entry.action, entry.resource_id) == (AuditAction.USER_CREATED, 5)
    assert entry.after == {
        "username": "ana",
        "full_name": "Ana Pérez",
        "role": "CASHIER",
        "active": True,
    }


def test_provisioning_creates_the_first_admin_outside_any_tenant():
    audit = FakeAuditTrail()

    _create_user(audit)

    assert audit.entries == []


def test_a_role_change_keeps_both_roles_by_name():
    users = Mock()
    users.get_by_id.return_value = User(
        id=5, username="ana", email="ana@example.com", password_hash="hash"
    )
    memberships = Mock()
    memberships.get_for.return_value = Membership(
        id=9, tenant_id=TENANT, user_id=5, role=Role.CASHIER
    )
    memberships.update.side_effect = lambda membership: membership
    audit = FakeAuditTrail()

    UpdateUserRoleCommandHandler(users, memberships, audit).handle(
        UpdateUserRoleCommand(tenant_id=TENANT, user_id=5, role=Role.MANAGER.value)
    )

    (entry,) = audit.entries
    assert entry.before == {"role": "CASHIER"}
    assert entry.after == {"role": "MANAGER"}


# Organization


def _branch() -> Branch:
    return Branch(id=2, establishment_code="002", name="Norte", address="Av. 1")


def test_a_branch_update_that_changes_nothing_leaves_no_entry():
    audit = FakeAuditTrail()

    UpdateBranchCommandHandler(_echo(_branch()), audit).handle(
        UpdateBranchCommand(
            branch_id=2, establishment_code="002", name="Norte", address="Av. 1"
        )
    )

    assert audit.entries == []


def test_a_deleted_branch_keeps_what_it_was():
    audit = FakeAuditTrail()

    DeleteBranchCommandHandler(_echo(_branch()), audit).handle(
        DeleteBranchCommand(branch_id=2)
    )

    (entry,) = audit.entries
    assert (entry.action, entry.branch_id) == (AuditAction.BRANCH_DELETED, 2)
    assert entry.before == {
        "establishment_code": "002",
        "name": "Norte",
        "address": "Av. 1",
        "is_active": True,
    }
