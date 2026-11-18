from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from wireup import Injected

from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.public_api.infra.dependencies import current_client, guarded
from src.public_api.infra.routes.common import READ, READ_ONE, WRITE
from src.public_api.infra.schemas.webhooks import (
    RotateWebhookSecretInput,
    WebhookDelivery,
    WebhookDeliveryListParams,
    WebhookEndpoint,
    WebhookEndpointInput,
    WebhookEndpointListParams,
    WebhookSecret,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.idempotency.requests import (
    Idempotency,
    IdempotentRequest,
    idempotent_request,
)
from src.shared.infra.validators import (
    DataResponse,
    Meta,
    PaginatedDataResponse,
    PaginatedMeta,
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


def _guarded() -> dict[str, Any]:
    """The public route's guard, plus the webhooks' own switch"""
    guard = guarded(Scope.WEBHOOKS_MANAGE)
    guard["dependencies"] = [*guard["dependencies"], Depends(webhooks_enabled)]
    return guard


def _page(result: dict, meta: Meta) -> PaginatedMeta:
    return meta.with_pagination(
        total=result["total"], limit=result["limit"], offset=result["offset"]
    )


class ApiWebhookEndpointRouter:
    """`/api/v1/webhook-endpoints`: the client's own endpoints (S6.4)"""

    def __init__(self):
        self.router = APIRouter()
        route = self.router
        route.get(
            "",
            response_model=PaginatedDataResponse[WebhookEndpoint],
            summary="List webhook endpoints",
            responses=READ,
            **_guarded(),
        )(self.list)
        route.post(
            "",
            response_model=DataResponse[WebhookEndpoint],
            status_code=201,
            summary="Create a webhook endpoint",
            responses=WRITE,
            **_guarded(),
        )(self.create)
        route.get(
            "/{endpoint_id}",
            response_model=DataResponse[WebhookEndpoint],
            summary="Get a webhook endpoint",
            responses=READ_ONE,
            **_guarded(),
        )(self.get)
        route.put(
            "/{endpoint_id}",
            response_model=DataResponse[WebhookEndpoint],
            summary="Update a webhook endpoint",
            responses=WRITE,
            **_guarded(),
        )(self.update)
        route.delete(
            "/{endpoint_id}",
            status_code=204,
            summary="Delete a webhook endpoint",
            responses=WRITE,
            **_guarded(),
        )(self.delete)
        route.post(
            "/{endpoint_id}/enable",
            response_model=DataResponse[WebhookEndpoint],
            summary="Enable a webhook endpoint",
            responses=WRITE,
            **_guarded(),
        )(self.enable)
        route.post(
            "/{endpoint_id}/disable",
            response_model=DataResponse[WebhookEndpoint],
            summary="Disable a webhook endpoint",
            responses=WRITE,
            **_guarded(),
        )(self.disable)
        route.get(
            "/{endpoint_id}/secret",
            response_model=DataResponse[WebhookSecret],
            summary="Get its signing secret",
            responses=READ_ONE,
            **_guarded(),
        )(self.secret)
        route.post(
            "/{endpoint_id}/rotate-secret",
            response_model=DataResponse[WebhookEndpoint],
            summary="Rotate its signing secret",
            responses=WRITE,
            **_guarded(),
        )(self.rotate_secret)
        route.post(
            "/{endpoint_id}/test",
            response_model=DataResponse[WebhookDelivery],
            status_code=201,
            summary="Send a test event",
            responses=WRITE,
            **_guarded(),
        )(self.test)
        route.get(
            "/{endpoint_id}/deliveries",
            response_model=PaginatedDataResponse[WebhookDelivery],
            summary="List its deliveries",
            responses=READ_ONE,
            **_guarded(),
        )(self.deliveries)
        route.post(
            "/{endpoint_id}/deliveries/{delivery_id}/retry",
            response_model=DataResponse[WebhookDelivery],
            summary="Send a delivery again",
            responses=WRITE,
            **_guarded(),
        )(self.retry)

    def list(
        self,
        handler: Injected[ListWebhookEndpointsQueryHandler],
        params: Annotated[WebhookEndpointListParams, Query()],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[WebhookEndpoint]:
        """This client's webhook endpoints, by id."""
        result = handler.handle(
            ListWebhookEndpointsQuery(
                as_client_id=client.client_id,
                status=params.status,
                limit=params.limit,
                offset=params.offset,
            )
        )
        return PaginatedDataResponse(
            data=[WebhookEndpoint.model_validate(i) for i in result["items"]],
            meta=_page(result, meta),
        )

    def create(
        self,
        body: WebhookEndpointInput,
        handler: Injected[CreateWebhookEndpointCommandHandler],
        idempotency: Injected[Idempotency],
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint] | JSONResponse:
        """Register an HTTPS URL that receives the events of `eventTypes`,
        signed with a new secret: read it with `GET …/{id}/secret`. Each event
        needs the read scope of its resource on this client
        (`INSUFFICIENT_SCOPE`), and it only gets the ones of its branches. A URL
        that isn't HTTPS or resolves to a private or local address:
        `WEBHOOK_URL_NOT_ALLOWED`. At most 20 per company
        (`WEBHOOK_ENDPOINT_LIMIT_REACHED`). Requires `Idempotency-Key`."""

        def respond() -> DataResponse[WebhookEndpoint]:
            result = handler.handle(
                CreateWebhookEndpointCommand(
                    url=body.url,
                    event_types=body.event_types,
                    description=body.description,
                    exclude_own_changes=body.exclude_own_changes,
                    integration_client_id=client.client_id,
                )
            )
            return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def get(
        self,
        endpoint_id: int,
        handler: Injected[GetWebhookEndpointQueryHandler],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint]:
        """One of this client's webhook endpoints."""
        result = handler.handle(
            GetWebhookEndpointQuery(
                endpoint_id=endpoint_id, as_client_id=client.client_id
            )
        )
        return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

    def update(
        self,
        endpoint_id: int,
        body: WebhookEndpointInput,
        handler: Injected[UpdateWebhookEndpointCommandHandler],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint]:
        """Replace its URL (checked again), events, description and
        `excludeOwnChanges`."""
        result = handler.handle(
            UpdateWebhookEndpointCommand(
                endpoint_id=endpoint_id,
                url=body.url,
                event_types=body.event_types,
                description=body.description,
                exclude_own_changes=body.exclude_own_changes,
                as_client_id=client.client_id,
            )
        )
        return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

    def delete(
        self,
        endpoint_id: int,
        handler: Injected[DeleteWebhookEndpointCommandHandler],
        client: IntegrationPrincipal = Depends(current_client),
    ) -> None:
        """Delete it with its history: what was on its way is not sent."""
        handler.handle(
            DeleteWebhookEndpointCommand(
                endpoint_id=endpoint_id, as_client_id=client.client_id
            )
        )

    def enable(
        self,
        endpoint_id: int,
        handler: Injected[EnableWebhookEndpointCommandHandler],
        idempotency: Injected[Idempotency],
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint] | JSONResponse:
        """Back to receiving: its pending deliveries go on; the failed ones are
        sent again with `…/deliveries/{deliveryId}/retry`. Requires
        `Idempotency-Key`."""

        def respond() -> DataResponse[WebhookEndpoint]:
            result = handler.handle(
                EnableWebhookEndpointCommand(
                    endpoint_id=endpoint_id, as_client_id=client.client_id
                )
            )
            return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def disable(
        self,
        endpoint_id: int,
        handler: Injected[DisableWebhookEndpointCommandHandler],
        idempotency: Injected[Idempotency],
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint] | JSONResponse:
        """Stop sending to it; what it had pending waits until it is enabled.
        Requires `Idempotency-Key`."""

        def respond() -> DataResponse[WebhookEndpoint]:
            result = handler.handle(
                DisableWebhookEndpointCommand(
                    endpoint_id=endpoint_id, as_client_id=client.client_id
                )
            )
            return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def secret(
        self,
        endpoint_id: int,
        handler: Injected[GetWebhookSecretQueryHandler],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookSecret]:
        """The secret that signs its messages and, during a rotation, the
        previous one. Keep it on your server only."""
        result = handler.handle(
            GetWebhookSecretQuery(
                endpoint_id=endpoint_id, as_client_id=client.client_id
            )
        )
        return DataResponse(data=WebhookSecret.model_validate(result), meta=meta)

    def rotate_secret(
        self,
        endpoint_id: int,
        handler: Injected[RotateWebhookSecretCommandHandler],
        idempotency: Injected[Idempotency],
        body: RotateWebhookSecretInput | None = None,
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookEndpoint] | JSONResponse:
        """A new secret (read it with `GET …/secret`); the current one keeps
        signing next to it for `previousExpiresInHours` (24 by default), so the
        receiver can switch without losing messages. Requires
        `Idempotency-Key`."""
        hours = (body or RotateWebhookSecretInput()).previous_expires_in_hours

        def respond() -> DataResponse[WebhookEndpoint]:
            result = handler.handle(
                RotateWebhookSecretCommand(
                    endpoint_id=endpoint_id,
                    previous_expires_in_hours=hours,
                    as_client_id=client.client_id,
                )
            )
            return DataResponse(data=WebhookEndpoint.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def test(
        self,
        endpoint_id: int,
        handler: Injected[SendTestWebhookCommandHandler],
        idempotency: Injected[Idempotency],
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookDelivery] | JSONResponse:
        """Queue a `webhook.test` event to it: its delivery, pending, which the
        worker sends in a moment. A disabled endpoint:
        `WEBHOOK_ENDPOINT_DISABLED`. Requires `Idempotency-Key`."""

        def respond() -> DataResponse[WebhookDelivery]:
            result = handler.handle(
                SendTestWebhookCommand(
                    endpoint_id=endpoint_id, as_client_id=client.client_id
                )
            )
            return DataResponse(data=WebhookDelivery.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)

    def deliveries(
        self,
        endpoint_id: int,
        handler: Injected[ListWebhookDeliveriesQueryHandler],
        params: Annotated[WebhookDeliveryListParams, Query()],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[WebhookDelivery]:
        """Its deliveries of the last 30 days, newest first."""
        result = handler.handle(
            ListWebhookDeliveriesQuery(
                endpoint_id=endpoint_id,
                as_client_id=client.client_id,
                status=params.status,
                event_type=params.event_type,
                limit=params.limit,
                offset=params.offset,
            )
        )
        return PaginatedDataResponse(
            data=[WebhookDelivery.model_validate(i) for i in result["items"]],
            meta=_page(result, meta),
        )

    def retry(
        self,
        endpoint_id: int,
        delivery_id: int,
        handler: Injected[RetryWebhookDeliveryCommandHandler],
        idempotency: Injected[Idempotency],
        client: IntegrationPrincipal = Depends(current_client),
        idempotent: IdempotentRequest | None = Depends(idempotent_request),
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WebhookDelivery] | JSONResponse:
        """Send a delivered or failed delivery again, with its attempts from the
        start and the same `webhook-id`. A pending one:
        `WEBHOOK_DELIVERY_PENDING`; a disabled endpoint:
        `WEBHOOK_ENDPOINT_DISABLED`. Requires `Idempotency-Key`."""

        def respond() -> DataResponse[WebhookDelivery]:
            result = handler.handle(
                RetryWebhookDeliveryCommand(
                    endpoint_id=endpoint_id,
                    delivery_id=delivery_id,
                    as_client_id=client.client_id,
                )
            )
            return DataResponse(data=WebhookDelivery.model_validate(result), meta=meta)

        return idempotency.run(idempotent, respond)
