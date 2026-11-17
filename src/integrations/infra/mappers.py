from typing import Any, overload

from wireup import injectable

from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import IntegrationEnvironment
from src.integrations.domain.entities import (
    ClientSecret,
    IntegrationClient,
    IntegrationClientStatus,
)
from src.integrations.infra.models import ClientSecretModel, IntegrationClientModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class IntegrationClientMapper(Mapper[IntegrationClient, IntegrationClientModel]):
    """By hand: the scopes, branches and networks are sets in the entity and
    JSON lists in the table"""

    __entity__ = IntegrationClient

    @overload
    def to_entity(self, model: IntegrationClientModel) -> IntegrationClient: ...

    @overload
    def to_entity(self, model: None) -> None: ...

    def to_entity(
        self, model: IntegrationClientModel | None
    ) -> IntegrationClient | None:
        if model is None:
            return None
        return IntegrationClient(
            id=model.id,
            public_id=model.public_id,
            name=model.name,
            environment=IntegrationEnvironment(model.environment),
            status=IntegrationClientStatus(model.status),
            # A scope retired from the catalog stops counting
            scopes=frozenset(
                Scope(name) for name in model.scopes if name in Scope._value2member_map_
            ),
            branch_ids=frozenset(model.branch_ids) if model.branch_ids else None,
            allowed_ips=tuple(model.allowed_ips) if model.allowed_ips else None,
            last_used_at=model.last_used_at,
            revoked_at=model.revoked_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def to_dict(self, entity: IntegrationClient) -> dict[str, Any]:
        values: dict[str, Any] = {
            "public_id": entity.public_id,
            "name": entity.name,
            "environment": entity.environment.value,
            "status": entity.status.value,
            "scopes": sorted(scope.value for scope in entity.scopes),
            "branch_ids": sorted(entity.branch_ids) if entity.branch_ids else None,
            "allowed_ips": list(entity.allowed_ips) if entity.allowed_ips else None,
            "last_used_at": entity.last_used_at,
            "revoked_at": entity.revoked_at,
        }
        if entity.id is not None:
            values["id"] = entity.id
        return values


@injectable(lifetime="singleton")
class ClientSecretMapper(Mapper[ClientSecret, ClientSecretModel]):
    __entity__ = ClientSecret
    __exclude_fields__ = frozenset({"created_at"})
