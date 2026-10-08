from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.inventory.warehouse.app.commands.create import (
    CreateWarehouseCommand,
    CreateWarehouseCommandHandler,
)
from src.inventory.warehouse.app.commands.delete import (
    DeleteWarehouseCommand,
    DeleteWarehouseCommandHandler,
)
from src.inventory.warehouse.app.commands.update import (
    UpdateWarehouseCommand,
    UpdateWarehouseCommandHandler,
)
from src.inventory.warehouse.app.queries.get_warehouse import (
    GetAllWarehousesQuery,
    GetAllWarehousesQueryHandler,
    GetWarehouseByIdQuery,
    GetWarehouseByIdQueryHandler,
)
from src.inventory.warehouse.infra.validators import (
    WarehouseQueryParams,
    WarehouseRequest,
    WarehouseResponse,
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


class WarehouseRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        _read = [Depends(require_permission(Permission.STOCK_READ))]
        _write = [Depends(require_permission(Permission.WAREHOUSE_WRITE))]

        self.router.post(
            "",
            response_model=DataResponse[WarehouseResponse],
            summary="Create warehouse",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[WarehouseResponse],
            summary="Update warehouse",
            responses=RESPONSES_COMMAND,
            dependencies=_write,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete warehouse",
            responses=RESPONSES_DELETE,
            dependencies=_write,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[WarehouseResponse],
            summary="Get all warehouses",
            responses=RESPONSES_LIST,
            dependencies=_read,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[WarehouseResponse],
            summary="Get warehouse by ID",
            responses=RESPONSES_QUERY,
            dependencies=_read,
        )(self.get_by_id)

    def create(
        self,
        body: WarehouseRequest,
        handler: Injected[CreateWarehouseCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WarehouseResponse]:
        """Create a new warehouse facility."""
        result = handler.handle(
            CreateWarehouseCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(data=WarehouseResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: WarehouseRequest,
        handler: Injected[UpdateWarehouseCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WarehouseResponse]:
        """Update a warehouse's name, code, address, or active status."""
        result = handler.handle(
            UpdateWarehouseCommand(warehouse_id=id, **body.model_dump(by_alias=False))
        )
        return DataResponse(data=WarehouseResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeleteWarehouseCommandHandler]) -> None:
        """Delete a warehouse. Fails if it contains locations with stock."""
        handler.handle(DeleteWarehouseCommand(warehouse_id=id))

    def get_all(
        self,
        handler: Injected[GetAllWarehousesQueryHandler],
        query_params: WarehouseQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[WarehouseResponse]:
        """List warehouses. Optionally filter by active status."""
        result = handler.handle(
            GetAllWarehousesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[WarehouseResponse.model_validate(w) for w in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetWarehouseByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[WarehouseResponse]:
        """Retrieve a warehouse by its ID."""
        result = handler.handle(GetWarehouseByIdQuery(warehouse_id=id))
        return DataResponse(data=WarehouseResponse.model_validate(result), meta=meta)
