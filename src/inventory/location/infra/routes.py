from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.inventory.location.app.commands.create import (
    CreateLocationCommand,
    CreateLocationCommandHandler,
)
from src.inventory.location.app.commands.delete import (
    DeleteLocationCommand,
    DeleteLocationCommandHandler,
)
from src.inventory.location.app.commands.update import (
    UpdateLocationCommand,
    UpdateLocationCommandHandler,
)
from src.inventory.location.app.queries.get_location import (
    GetAllLocationsQuery,
    GetAllLocationsQueryHandler,
    GetLocationByIdQuery,
    GetLocationByIdQueryHandler,
)
from src.inventory.location.infra.validators import (
    LocationQueryParams,
    LocationRequest,
    LocationResponse,
)
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


class LocationRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.STOCK_READ))]
        _write = [Depends(require_permission(Permission.LOCATION_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[LocationResponse],
            summary="Create location",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[LocationResponse],
            summary="Update location",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete location",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[LocationResponse],
            summary="Get all locations",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[LocationResponse],
            summary="Get location by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)

    def create(
        self,
        body: LocationRequest,
        handler: Injected[CreateLocationCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[LocationResponse]:
        """Create a storage location within a warehouse."""
        result = handler.handle(
            CreateLocationCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(data=LocationResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: LocationRequest,
        handler: Injected[UpdateLocationCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[LocationResponse]:
        """Update a storage location."""
        result = handler.handle(
            UpdateLocationCommand(location_id=id, **body.model_dump(by_alias=False))
        )
        return DataResponse(data=LocationResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeleteLocationCommandHandler]) -> None:
        """Delete a storage location. Fails if stock exists at this location."""
        handler.handle(DeleteLocationCommand(location_id=id))

    def get_all(
        self,
        handler: Injected[GetAllLocationsQueryHandler],
        query_params: LocationQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[LocationResponse]:
        """List storage locations. Optionally filter by warehouse or active status."""
        result = handler.handle(
            GetAllLocationsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[LocationResponse.model_validate(loc) for loc in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetLocationByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[LocationResponse]:
        """Retrieve a storage location by its ID."""
        result = handler.handle(GetLocationByIdQuery(location_id=id))
        return DataResponse(data=LocationResponse.model_validate(result), meta=meta)
