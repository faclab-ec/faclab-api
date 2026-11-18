from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_DELETE,
    RESPONSES_LIST,
    RESPONSES_QUERY,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)
from src.webhooks.app.commands.endpoints import (
    CreateWebhookEndpointCommand,
    CreateWebhookEndpointCommandHandler,
    DeleteWebhookEndpointCommand,
    DeleteWebhookEndpointCommandHandler,
    DisableWebhookEndpointCommand,
    DisableWebhookEndpointCommandHandler,
    EnableWebhookEndpointCommand,
    EnableWebhookEndpointCommandHandler,
    RetryWebhookDeliveryCommand,
    RetryWebhookDeliveryCommandHandler,
    RotateWebhookSecretCommand,
    RotateWebhookSecretCommandHandler,
    SendTestWebhookCommand,
    SendTestWebhookCommandHandler,
    UpdateWebhookEndpointCommand,
    UpdateWebhookEndpointCommandHandler,
)
from src.webhooks.app.queries.endpoints import (
    GetWebhookEndpointQuery,
    GetWebhookEndpointQueryHandler,
    GetWebhookSecretQuery,
    GetWebhookSecretQueryHandler,
    ListWebhookDeliveriesQuery,
    ListWebhookDeliveriesQueryHandler,
    ListWebhookEndpointsQuery,
    ListWebhookEndpointsQueryHandler,
)
from src.webhooks.infra.dependencies import webhooks_enabled
from src.webhooks.infra.validators import (
    RotateWebhookSecretRequest,
    WebhookDeliveryQueryParams,
    WebhookDeliveryResponse,
    WebhookEndpointQueryParams,
    WebhookEndpointRequest,
    WebhookEndpointResponse,
    WebhookEndpointUpdateRequest,
    WebhookSecretResponse,
)

_MANAGE = [
    Depends(webhooks_enabled),
    Depends(require_permission(Permission.INTEGRATION_MANAGE)),
]


class WebhookEndpointRouter:
    """Every webhook endpoint of the tenant (S6.4): `/api/admin/webhook-endpoints`.
    An integration client manages its own ones at `/api/v1/webhook-endpoints`."""

    def __init__(self):
        self.router = APIRouter()
        route = self.router
        route.post(
            "",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Create webhook endpoint",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.create)
        route.get(
            "",
            response_model=PaginatedDataResponse[WebhookEndpointResponse],
            summary="List webhook endpoints",
            responses=RESPONSES_LIST,
            dependencies=_MANAGE,
        )(self.get_all)
        route.get(
            "/{id}",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Get webhook endpoint",
            responses=RESPONSES_QUERY,
            dependencies=_MANAGE,
        )(self.get_by_id)
        route.put(
            "/{id}",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Update webhook endpoint",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.update)
        route.delete(
            "/{id}",
            summary="Delete webhook endpoint",
            responses=RESPONSES_DELETE,
            dependencies=_MANAGE,
        )(self.delete)
        route.post(
            "/{id}/enable",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Enable webhook endpoint",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.enable)
        route.post(
            "/{id}/disable",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Disable webhook endpoint",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.disable)
        route.get(
            "/{id}/secret",
            response_model=DataResponse[WebhookSecretResponse],
            summary="Get its signing secret",
            responses=RESPONSES_QUERY,
            dependencies=_MANAGE,
        )(self.secret)
        route.post(
            "/{id}/rotate-secret",
            response_model=DataResponse[WebhookEndpointResponse],
            summary="Rotate its signing secret",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.rotate_secret)
        route.post(
            "/{id}/test",
            response_model=DataResponse[WebhookDeliveryResponse],
            summary="Send a test event",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.test)
        route.get(
            "/{id}/deliveries",
            response_model=PaginatedDataResponse[WebhookDeliveryResponse],
            summary="List its deliveries",
            responses=RESPONSES_LIST,
            dependencies=_MANAGE,
        )(self.deliveries)
        route.post(
            "/{id}/deliveries/{delivery_id}/retry",
            response_model=DataResponse[WebhookDeliveryResponse],
            summary="Send a delivery again",
            responses=RESPONSES_COMMAND,
            dependencies=_MANAGE,
        )(self.retry)

    def create(
        self,
        body: WebhookEndpointRequest,
        handler: Injected[CreateWebhookEndpointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """Register an HTTPS URL that receives the events of `eventTypes`,
        signed with a new secret (`GET …/{id}/secret`). A URL that isn't HTTPS
        or resolves to a private or local address: `WEBHOOK_URL_NOT_ALLOWED`
        (422). With `integrationClientId` it only gets what that client may read
        (`INSUFFICIENT_SCOPE`, 403, for an event it can't), and
        `excludeOwnChanges` skips the changes the client made. At most 20 per
        company (`WEBHOOK_ENDPOINT_LIMIT_REACHED`, 409)."""
        result = handler.handle(
            CreateWebhookEndpointCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def get_all(
        self,
        handler: Injected[ListWebhookEndpointsQueryHandler],
        query_params: WebhookEndpointQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[WebhookEndpointResponse]:
        """The tenant's webhook endpoints, of the company and of its integration
        clients, by ID."""
        result = handler.handle(
            ListWebhookEndpointsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[WebhookEndpointResponse.model_validate(i) for i in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetWebhookEndpointQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """A webhook endpoint, its secret only by its start."""
        result = handler.handle(GetWebhookEndpointQuery(endpoint_id=id))
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        id: int,
        body: WebhookEndpointUpdateRequest,
        handler: Injected[UpdateWebhookEndpointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """Change its URL (checked again), events, description and
        `excludeOwnChanges`. Its integration client stays."""
        result = handler.handle(
            UpdateWebhookEndpointCommand(
                endpoint_id=id, **body.model_dump(by_alias=False)
            )
        )
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def delete(
        self, id: int, handler: Injected[DeleteWebhookEndpointCommandHandler]
    ) -> None:
        """Delete it with its history: what was on its way is not sent."""
        handler.handle(DeleteWebhookEndpointCommand(endpoint_id=id))

    def enable(
        self,
        id: int,
        handler: Injected[EnableWebhookEndpointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """Back to receiving: its pending deliveries go on; the failed ones are
        sent again with `…/deliveries/{deliveryId}/retry`."""
        result = handler.handle(EnableWebhookEndpointCommand(endpoint_id=id))
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def disable(
        self,
        id: int,
        handler: Injected[DisableWebhookEndpointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """Stop sending to it; what it had pending waits until it is enabled."""
        result = handler.handle(DisableWebhookEndpointCommand(endpoint_id=id))
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def secret(
        self,
        id: int,
        handler: Injected[GetWebhookSecretQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookSecretResponse]:
        """The secret that signs its messages (`whsec_…`) and, during a rotation,
        the previous one."""
        result = handler.handle(GetWebhookSecretQuery(endpoint_id=id))
        return DataResponse(
            data=WebhookSecretResponse.model_validate(result), meta=meta
        )

    def rotate_secret(
        self,
        id: int,
        handler: Injected[RotateWebhookSecretCommandHandler],
        body: RotateWebhookSecretRequest | None = None,
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpointResponse]:
        """A new secret; the current one keeps signing next to it for
        `previousExpiresInHours` (24 by default)."""
        body = body or RotateWebhookSecretRequest()
        result = handler.handle(
            RotateWebhookSecretCommand(
                endpoint_id=id, previous_expires_in_hours=body.previous_expires_in_hours
            )
        )
        return DataResponse(
            data=WebhookEndpointResponse.model_validate(result), meta=meta
        )

    def test(
        self,
        id: int,
        handler: Injected[SendTestWebhookCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookDeliveryResponse]:
        """Queue a `webhook.test` event to it; the worker sends it in a moment.
        A disabled endpoint: `WEBHOOK_ENDPOINT_DISABLED` (409)."""
        result = handler.handle(SendTestWebhookCommand(endpoint_id=id))
        return DataResponse(
            data=WebhookDeliveryResponse.model_validate(result), meta=meta
        )

    def deliveries(
        self,
        id: int,
        handler: Injected[ListWebhookDeliveriesQueryHandler],
        query_params: WebhookDeliveryQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[WebhookDeliveryResponse]:
        """Its deliveries of the last 30 days, newest first."""
        result = handler.handle(
            ListWebhookDeliveriesQuery(
                endpoint_id=id, **query_params.model_dump(exclude_none=True)
            )
        )
        return PaginatedDataResponse(
            data=[WebhookDeliveryResponse.model_validate(i) for i in result["items"]],
            meta=meta.with_pagination(
                total=result["total"], limit=result["limit"], offset=result["offset"]
            ),
        )

    def retry(
        self,
        id: int,
        delivery_id: int,
        handler: Injected[RetryWebhookDeliveryCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookDeliveryResponse]:
        """Send a delivered or failed delivery again, with its attempts from the
        start and the same `webhook-id`. A pending one:
        `WEBHOOK_DELIVERY_PENDING` (409)."""
        result = handler.handle(
            RetryWebhookDeliveryCommand(endpoint_id=id, delivery_id=delivery_id)
        )
        return DataResponse(
            data=WebhookDeliveryResponse.model_validate(result), meta=meta
        )
