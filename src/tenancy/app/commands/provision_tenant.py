from dataclasses import dataclass

from wireup import injectable

from src.auth.app.commands.create_user import (
    CreateUserCommand,
    CreateUserCommandHandler,
)
from src.auth.app.repositories import UserRepository
from src.auth.domain.entities import Role
from src.shared.app.commands import Command, CommandHandler
from src.tenancy.app.repositories import MembershipRepository, TenantRepository
from src.tenancy.domain.entities import Membership, Tenant
from src.tenancy.domain.exceptions import AdminPasswordRequiredError


@dataclass
class ProvisionTenantCommand(Command):
    ruc: str = ""
    legal_name: str = ""
    trade_name: str | None = None
    admin_username: str = ""
    admin_email: str = ""
    # Only used to create the admin user; an existing user keeps its password
    admin_password: str | None = None
    admin_full_name: str | None = None


@injectable(lifetime="scoped")
class ProvisionTenantCommandHandler(CommandHandler[ProvisionTenantCommand, dict]):
    """Da de alta una empresa con su primer administrador. Idempotente: repetirlo
    reutiliza la empresa (por RUC), el usuario (por nombre de usuario) y la
    membresía, que queda como administrador activo.

    Un usuario que ya existe (por ejemplo, el contador de otra empresa) entra
    con su contraseña de siempre.
    """

    def __init__(
        self,
        tenants: TenantRepository,
        memberships: MembershipRepository,
        users: UserRepository,
        create_user: CreateUserCommandHandler,
    ):
        self.tenants = tenants
        self.memberships = memberships
        self.users = users
        self.create_user = create_user

    def _handle(self, command: ProvisionTenantCommand) -> dict:
        tenant = Tenant(
            ruc=command.ruc,
            legal_name=command.legal_name,
            trade_name=command.trade_name,
        )
        existing = self.tenants.get_by_ruc(tenant.ruc)
        tenant_created = existing is None
        tenant = existing or self.tenants.add(tenant)

        user = self.users.get_by_username(command.admin_username)
        user_created = user is None
        membership_created = user is None
        if user is None:
            if not command.admin_password:
                raise AdminPasswordRequiredError()
            created = self.create_user.handle(
                CreateUserCommand(
                    tenant_id=tenant.id,
                    username=command.admin_username,
                    email=command.admin_email,
                    password=command.admin_password,
                    role=Role.ADMIN.value,
                    full_name=command.admin_full_name,
                )
            )
            user_id = created["id"]
        else:
            user_id = user.require_id()
            membership = self.memberships.get_for(tenant.id, user_id, for_update=True)
            membership_created = membership is None
            if membership is None:
                self.memberships.create(
                    Membership(tenant_id=tenant.id, user_id=user_id, role=Role.ADMIN)
                )
            elif not (membership.is_admin and membership.active):
                membership.change_role(Role.ADMIN)
                membership.activate()
                self.memberships.update(membership)

        return {
            "tenant_id": tenant.id,
            "tenant_created": tenant_created,
            "user_id": user_id,
            "user_created": user_created,
            "membership_created": membership_created,
        }
