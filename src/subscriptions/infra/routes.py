from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import RESPONSES_QUERY, DataResponse, Meta
from src.subscriptions.app.queries.subscription import (
    GetSubscriptionQuery,
    GetSubscriptionQueryHandler,
)
from src.subscriptions.infra.validators import SubscriptionResponse


class SubscriptionRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=DataResponse[SubscriptionResponse],
            summary="Get the company's plan and usage",
            responses=RESPONSES_QUERY,
            dependencies=[Depends(require_permission(Permission.ORGANIZATION_READ))],
        )(self.get)

    def get(
        self,
        handler: Injected[GetSubscriptionQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[SubscriptionResponse]:
        """The company's plan, the status of its subscription, what it uses of
        each limit and its electronic documents of the last six months. Plans
        and subscriptions are changed by the platform."""
        result = handler.handle(GetSubscriptionQuery())
        return DataResponse(data=SubscriptionResponse.model_validate(result), meta=meta)
