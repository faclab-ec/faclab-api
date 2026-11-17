from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.integrations.app.commands.clients import (
    CreateIntegrationClientCommand,
    CreateIntegrationClientCommandHandler,
    RevokeIntegrationClientCommand,
    RevokeIntegrationClientCommandHandler,
    UpdateIntegrationClientCommand,
    UpdateIntegrationClientCommandHandler,
)
from src.integrations.app.commands.secrets import (
    CreateClientSecretCommand,
    CreateClientSecretCommandHandler,
    RevokeClientSecretCommand,
    RevokeClientSecretCommandHandler,
)
from src.integrations.app.queries.clients import (
    GetIntegrationClientQuery,
    GetIntegrationClientQueryHandler,
    GetIntegrationUsageQuery,
    GetIntegrationUsageQueryHandler,
    ListIntegrationClientsQuery,
    ListIntegrationClientsQueryHandler,
)
from src.integrations.infra.validators import (
    ClientSecretResponse,
    CreatedClientSecretResponse,
    CreatedIntegrationClientResponse,
    IntegrationClientQueryParams,
    IntegrationClientRequest,
    IntegrationClientResponse,
    IntegrationUsageQueryParams,
    IntegrationUsageResponse,
    NewClientSecretRequest,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    ListResponse,
    Meta,
    PaginatedDataResponse,
)

_MANAGE = [Depends(require_permission(Permission.INTEGRATION_MANAGE))]


class IntegrationRouter:
    """The tenant's integration clients (S6.2): `/api/admin/integrations`"""

    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "",
            response_model=DataResponse[CreatedIntegrationClientResponse],
            summary="Create integration client",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[IntegrationClientResponse],
            summary="List integration clients",
            responses=RESPONSES_LIST,
            dependencies=_MANAGE,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[IntegrationClientResponse],
            summary="Get integration client",
            responses=RESPONSES_QUERY,
            dependencies=_MANAGE,
        )(self.get_by_id)
        self.router.put(
            "/{id}",
            response_model=DataResponse[IntegrationClientResponse],
            summary="Update integration client",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.update)
        self.router.post(
            "/{id}/revoke",
            response_model=DataResponse[IntegrationClientResponse],
            summary="Revoke integration client",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.revoke)
        self.router.post(
            "/{id}/secrets",
            response_model=DataResponse[CreatedClientSecretResponse],
            summary="Add a secret (rotation)",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.create_secret)
        self.router.post(
            "/{id}/secrets/{secret_id}/revoke",
            response_model=DataResponse[ClientSecretResponse],
            summary="Revoke a secret",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.revoke_secret)
        self.router.get(
            "/{id}/usage",
            response_model=ListResponse[IntegrationUsageResponse],
            summary="Usage per day",
            responses=RESPONSES_QUERY,
            dependencies=_MANAGE,
        )(self.usage)

    def create(
        self,
        body: IntegrationClientRequest,
        handler: Injected[CreateIntegrationClientCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CreatedIntegrationClientResponse]:
        """Create a client of this deployment's environment (`fl_live_…` in
        production, `fl_test_…` in a sandbox) with its first secret.
        `clientSecret` is shown only in this response: it is kept as a hash.
        A scope outside the tenant's plan: `SCOPE_NOT_IN_PLAN` (409); a branch
        that isn't the tenant's: `REFERENCE_NOT_FOUND` (422)."""
        result = handler.handle(
            CreateIntegrationClientCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(
            data=CreatedIntegrationClientResponse.model_validate(result), meta=meta
        )

    def get_all(
        self,
        handler: Injected[ListIntegrationClientsQueryHandler],
        query_params: IntegrationClientQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[IntegrationClientResponse]:
        """The tenant's integration clients with their secrets (never their
        value), by ID."""
        result = handler.handle(
            ListIntegrationClientsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[
                IntegrationClientResponse.model_validate(item)
                for item in result["items"]
            ],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetIntegrationClientQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[IntegrationClientResponse]:
        """An integration client with its secrets (never their value)."""
        result = handler.handle(GetIntegrationClientQuery(client_id=id))
        return DataResponse(
            data=IntegrationClientResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        id: int,
        body: IntegrationClientRequest,
        handler: Injected[UpdateIntegrationClientCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[IntegrationClientResponse]:
        """Change its name, scopes, branches and addresses. The tokens it
        already has narrow to them within a minute. A revoked client:
        `INTEGRATION_CLIENT_REVOKED` (409)."""
        result = handler.handle(
            UpdateIntegrationClientCommand(
                client_id=id, **body.model_dump(by_alias=False)
            )
        )
        return DataResponse(
            data=IntegrationClientResponse.model_validate(result), meta=meta
        )

    def revoke(
        self,
        id: int,
        handler: Injected[RevokeIntegrationClientCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[IntegrationClientResponse]:
        """Revoke the client for good: its secrets are revoked, it gets no more
        tokens and the ones it has stop working within a minute."""
        result = handler.handle(RevokeIntegrationClientCommand(client_id=id))
        return DataResponse(
            data=IntegrationClientResponse.model_validate(result), meta=meta
        )

    def create_secret(
        self,
        id: int,
        body: NewClientSecretRequest,
        handler: Injected[CreateClientSecretCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[CreatedClientSecretResponse]:
        """Rotation: a new secret, shown only in this response, next to the
        current one. At most two are active (`INTEGRATION_SECRET_LIMIT_REACHED`,
        409); `previousExpiresInDays` makes the current ones expire."""
        result = handler.handle(
            CreateClientSecretCommand(client_id=id, **body.model_dump(by_alias=False))
        )
        return DataResponse(
            data=CreatedClientSecretResponse.model_validate(result), meta=meta
        )

    def revoke_secret(
        self,
        id: int,
        secret_id: int,
        handler: Injected[RevokeClientSecretCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[ClientSecretResponse]:
        """Revoke a secret: it gets no more tokens, and the ones obtained with
        it stop working within a minute."""
        result = handler.handle(
            RevokeClientSecretCommand(client_id=id, secret_id=secret_id)
        )
        return DataResponse(data=ClientSecretResponse.model_validate(result), meta=meta)

    def usage(
        self,
        id: int,
        handler: Injected[GetIntegrationUsageQueryHandler],
        query_params: IntegrationUsageQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[IntegrationUsageResponse]:
        """Tokens obtained and refused, requests and errors per day (the last
        30 days by default)."""
        result = handler.handle(
            GetIntegrationUsageQuery(client_id=id, **query_params.model_dump())
        )
        return ListResponse(
            data=[IntegrationUsageResponse.model_validate(row) for row in result],
            meta=meta,
        )
