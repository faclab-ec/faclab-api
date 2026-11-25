from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.onboarding.app.queries.get_onboarding import (
    GetOnboardingQuery,
    GetOnboardingQueryHandler,
)
from src.onboarding.infra.validators import OnboardingResponse
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import RESPONSES_QUERY, DataResponse, Meta


class OnboardingRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.get(
            "",
            response_model=DataResponse[OnboardingResponse],
            summary="The company's onboarding checklist",
            responses=RESPONSES_QUERY,
            dependencies=[Depends(require_permission(Permission.ORGANIZATION_READ))],
        )(self.get)

    def get(
        self,
        handler: Injected[GetOnboardingQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[OnboardingResponse]:
        """Which steps of the company's setup exist (branches, emission points,
        terminals, more users, an initial import), derived from its data: the
        wizard can be resumed at any time. The fiscal profile, the certificate,
        the sequences and the readiness are faclab-invoicing's."""
        return DataResponse(
            data=OnboardingResponse.model_validate(
                handler.handle(GetOnboardingQuery())
            ),
            meta=meta,
        )
