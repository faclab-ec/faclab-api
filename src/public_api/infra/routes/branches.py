from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.principals import IntegrationPrincipal
from src.public_api.app.queries.branches import (
    ListApiBranchesQuery,
    ListApiBranchesQueryHandler,
)
from src.public_api.infra.dependencies import current_client, guarded
from src.public_api.infra.routes.common import READ
from src.public_api.infra.schemas.branches import Branch
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import ListResponse, Meta


class ApiBranchRouter:
    """`/api/v1/branches`"""

    def __init__(self):
        self.router = APIRouter()
        self.router.get(
            "",
            response_model=ListResponse[Branch],
            summary="List branches",
            responses=READ,
            **guarded(),
        )(self.list)

    def list(
        self,
        handler: Injected[ListApiBranchesQueryHandler],
        client: IntegrationPrincipal = Depends(current_client),
        meta: Meta = Depends(get_meta),
    ) -> ListResponse[Branch]:
        """The active branches this client may operate in (any scope), each with
        its active emission points and the active locations of its warehouses:
        a sale names one of each (`emissionPointId`, `locationId`) and the
        branch in `X-Branch-Id`."""
        result = handler.handle(ListApiBranchesQuery(branch_ids=client.branch_ids))
        return ListResponse(
            data=[Branch.model_validate(item) for item in result], meta=meta
        )
