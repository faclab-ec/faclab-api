from fastapi import APIRouter, Depends
from wireup import Injected

from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission
from src.organization.app.commands.branch import (
    CreateBranchCommand,
    CreateBranchCommandHandler,
    DeleteBranchCommand,
    DeleteBranchCommandHandler,
    UpdateBranchCommand,
    UpdateBranchCommandHandler,
)
from src.organization.app.commands.emission_point import (
    CreateEmissionPointCommand,
    CreateEmissionPointCommandHandler,
    DeleteEmissionPointCommand,
    DeleteEmissionPointCommandHandler,
    UpdateEmissionPointCommand,
    UpdateEmissionPointCommandHandler,
)
from src.organization.app.commands.pos_terminal import (
    CreatePosTerminalCommand,
    CreatePosTerminalCommandHandler,
    DeletePosTerminalCommand,
    DeletePosTerminalCommandHandler,
    UpdatePosTerminalCommand,
    UpdatePosTerminalCommandHandler,
)
from src.organization.app.queries.branch import (
    GetAllBranchesQuery,
    GetAllBranchesQueryHandler,
    GetBranchByIdQuery,
    GetBranchByIdQueryHandler,
)
from src.organization.app.queries.emission_point import (
    GetAllEmissionPointsQuery,
    GetAllEmissionPointsQueryHandler,
    GetEmissionPointByIdQuery,
    GetEmissionPointByIdQueryHandler,
)
from src.organization.app.queries.pos_terminal import (
    GetAllPosTerminalsQuery,
    GetAllPosTerminalsQueryHandler,
    GetPosTerminalByIdQuery,
    GetPosTerminalByIdQueryHandler,
)
from src.organization.infra.validators import (
    BranchQueryParams,
    BranchRequest,
    BranchResponse,
    CreateEmissionPointRequest,
    CreatePosTerminalRequest,
    EmissionPointQueryParams,
    EmissionPointResponse,
    PosTerminalQueryParams,
    PosTerminalResponse,
    UpdateEmissionPointRequest,
    UpdatePosTerminalRequest,
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

_READ = [Depends(require_permission(Permission.ORGANIZATION_READ))]
_WRITE = [Depends(require_permission(Permission.ORGANIZATION_WRITE))]


class BranchRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "",
            response_model=DataResponse[BranchResponse],
            summary="Create branch",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[BranchResponse],
            summary="Update branch",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete branch",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[BranchResponse],
            summary="Get all branches",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[BranchResponse],
            summary="Get branch by ID",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def create(
        self,
        body: BranchRequest,
        handler: Injected[CreateBranchCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[BranchResponse]:
        """Create a branch (SRI establishment). The establishment code is unique
        in the tenant: `BRANCH_ESTABLISHMENT_CODE_ALREADY_EXISTS` (409)."""
        result = handler.handle(CreateBranchCommand(**body.model_dump(by_alias=False)))
        return DataResponse(data=BranchResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: BranchRequest,
        handler: Injected[UpdateBranchCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[BranchResponse]:
        """Update a branch's code, name, address or active status."""
        result = handler.handle(
            UpdateBranchCommand(branch_id=id, **body.model_dump(by_alias=False))
        )
        return DataResponse(data=BranchResponse.model_validate(result), meta=meta)

    def delete(self, id: int, handler: Injected[DeleteBranchCommandHandler]) -> None:
        """Delete a branch. The main branch can't be deleted
        (`MAIN_BRANCH_DELETION`, 409), nor one with warehouses, emission points,
        terminals or user accesses (`RECORD_IN_USE`, 409)."""
        handler.handle(DeleteBranchCommand(branch_id=id))

    def get_all(
        self,
        handler: Injected[GetAllBranchesQueryHandler],
        query_params: BranchQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[BranchResponse]:
        """List the tenant's branches. Optionally filter by active status."""
        result = handler.handle(
            GetAllBranchesQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[BranchResponse.model_validate(b) for b in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetBranchByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[BranchResponse]:
        """Retrieve a branch by its ID."""
        result = handler.handle(GetBranchByIdQuery(branch_id=id))
        return DataResponse(data=BranchResponse.model_validate(result), meta=meta)


class EmissionPointRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "",
            response_model=DataResponse[EmissionPointResponse],
            summary="Create emission point",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[EmissionPointResponse],
            summary="Update emission point",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete emission point",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[EmissionPointResponse],
            summary="Get all emission points",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[EmissionPointResponse],
            summary="Get emission point by ID",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def create(
        self,
        body: CreateEmissionPointRequest,
        handler: Injected[CreateEmissionPointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[EmissionPointResponse]:
        """Create an SRI emission point in a branch. The code is unique in the
        branch: `EMISSION_POINT_CODE_ALREADY_EXISTS` (409)."""
        result = handler.handle(
            CreateEmissionPointCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(
            data=EmissionPointResponse.model_validate(result), meta=meta
        )

    def update(
        self,
        id: int,
        body: UpdateEmissionPointRequest,
        handler: Injected[UpdateEmissionPointCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[EmissionPointResponse]:
        """Update an emission point's code, name or active status. Its branch
        doesn't change."""
        result = handler.handle(
            UpdateEmissionPointCommand(
                emission_point_id=id, **body.model_dump(by_alias=False)
            )
        )
        return DataResponse(
            data=EmissionPointResponse.model_validate(result), meta=meta
        )

    def delete(
        self, id: int, handler: Injected[DeleteEmissionPointCommandHandler]
    ) -> None:
        """Delete an emission point. One a terminal issues by can't be deleted
        (`RECORD_IN_USE`, 409)."""
        handler.handle(DeleteEmissionPointCommand(emission_point_id=id))

    def get_all(
        self,
        handler: Injected[GetAllEmissionPointsQueryHandler],
        query_params: EmissionPointQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[EmissionPointResponse]:
        """List emission points. Optionally filter by branch and active status."""
        result = handler.handle(
            GetAllEmissionPointsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[EmissionPointResponse.model_validate(p) for p in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetEmissionPointByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[EmissionPointResponse]:
        """Retrieve an emission point by its ID."""
        result = handler.handle(GetEmissionPointByIdQuery(emission_point_id=id))
        return DataResponse(
            data=EmissionPointResponse.model_validate(result), meta=meta
        )


class PosTerminalRouter:
    def __init__(self):
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        self.router.post(
            "",
            response_model=DataResponse[PosTerminalResponse],
            summary="Create POS terminal",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.create)
        self.router.put(
            "/{id}",
            response_model=DataResponse[PosTerminalResponse],
            summary="Update POS terminal",
            responses=RESPONSES_COMMAND,
            dependencies=_WRITE,
        )(self.update)
        self.router.delete(
            "/{id}",
            summary="Delete POS terminal",
            responses=RESPONSES_DELETE,
            dependencies=_WRITE,
        )(self.delete)
        self.router.get(
            "",
            response_model=PaginatedDataResponse[PosTerminalResponse],
            summary="Get all POS terminals",
            responses=RESPONSES_LIST,
            dependencies=_READ,
        )(self.get_all)
        self.router.get(
            "/{id}",
            response_model=DataResponse[PosTerminalResponse],
            summary="Get POS terminal by ID",
            responses=RESPONSES_QUERY,
            dependencies=_READ,
        )(self.get_by_id)

    def create(
        self,
        body: CreatePosTerminalRequest,
        handler: Injected[CreatePosTerminalCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PosTerminalResponse]:
        """Create a POS terminal. Its emission point must be of the same branch
        (`EMISSION_POINT_OUTSIDE_BRANCH`, 400) and its default location in a
        warehouse of that branch (`LOCATION_OUTSIDE_BRANCH`, 400)."""
        result = handler.handle(
            CreatePosTerminalCommand(**body.model_dump(by_alias=False))
        )
        return DataResponse(data=PosTerminalResponse.model_validate(result), meta=meta)

    def update(
        self,
        id: int,
        body: UpdatePosTerminalRequest,
        handler: Injected[UpdatePosTerminalCommandHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PosTerminalResponse]:
        """Update a terminal's emission point, default location, code, name or
        active status, checked against its branch, which doesn't change."""
        result = handler.handle(
            UpdatePosTerminalCommand(terminal_id=id, **body.model_dump(by_alias=False))
        )
        return DataResponse(data=PosTerminalResponse.model_validate(result), meta=meta)

    def delete(
        self, id: int, handler: Injected[DeletePosTerminalCommandHandler]
    ) -> None:
        """Delete a POS terminal."""
        handler.handle(DeletePosTerminalCommand(terminal_id=id))

    def get_all(
        self,
        handler: Injected[GetAllPosTerminalsQueryHandler],
        query_params: PosTerminalQueryParams = Depends(),
        meta: Meta = Depends(get_meta),
    ) -> PaginatedDataResponse[PosTerminalResponse]:
        """List POS terminals. Optionally filter by branch and active status."""
        result = handler.handle(
            GetAllPosTerminalsQuery(**query_params.model_dump(exclude_none=True))
        )
        return PaginatedDataResponse(
            data=[PosTerminalResponse.model_validate(t) for t in result["items"]],
            meta=meta.with_pagination(
                total=result["total"],
                limit=result["limit"],
                offset=result["offset"],
            ),
        )

    def get_by_id(
        self,
        id: int,
        handler: Injected[GetPosTerminalByIdQueryHandler],
        meta: Meta = Depends(get_meta),
    ) -> DataResponse[PosTerminalResponse]:
        """Retrieve a POS terminal by its ID."""
        result = handler.handle(GetPosTerminalByIdQuery(terminal_id=id))
        return DataResponse(data=PosTerminalResponse.model_validate(result), meta=meta)
