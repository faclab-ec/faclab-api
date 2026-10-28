from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.inventory.movement.app.commands.movement import (
    CreateMovementCommand,
    CreateMovementCommandHandler,
)
from src.inventory.movement.app.queries.movement import (
    GetAllMovementsQuery,
    GetAllMovementsQueryHandler,
)
from src.inventory.movement.infra.validators import (
    MovementQueryParams,
    MovementRequest,
    MovementResponse,
)
from src.shared.infra.dependencies import get_meta
from src.shared.infra.validators import (
    RESPONSES_COMMAND,
    RESPONSES_LIST,
    DataResponse,
    Meta,
    PaginatedDataResponse,
)


class MovementRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Sets up all the routes for the router."""
        _read = [Depends(require_permission(Permission.STOCK_READ))]
        _write = [Depends(require_permission(Permission.MOVEMENT_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[MovementResponse],
            summary="Save movement",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[MovementResponse],
            summary="Get all movements",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)

    def create(
        self,
        new_movement: MovementRequest,
        handler: Injected[CreateMovementCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[MovementResponse]:
        """Create a manual inventory movement (IN or OUT). Stock is updated
        automatically; an OUT only takes what the location has available. A
        manual movement has no document (`referenceType`/`referenceId`)."""
        result = handler.handle(
            CreateMovementCommand(
                **new_movement.model_dump(exclude_none=True), manual=True
            )
        )
        return DataResponse(data=MovementResponse.model_validate(result), meta=meta)

    def get_all(
        self,
        handler: Injected[GetAllMovementsQueryHandler],
        query_params: MovementQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[MovementResponse]:
        """List all inventory movements with optional filtering. Supports pagination."""
        result = handler.handle(
            GetAllMovementsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[MovementResponse.model_validate(m) for m in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )
