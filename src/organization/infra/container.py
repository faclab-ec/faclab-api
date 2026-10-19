from src.organization.app.commands.branch import (
    CreateBranchCommandHandler,
    DeleteBranchCommandHandler,
    UpdateBranchCommandHandler,
)
from src.organization.app.commands.emission_point import (
    CreateEmissionPointCommandHandler,
    DeleteEmissionPointCommandHandler,
    UpdateEmissionPointCommandHandler,
)
from src.organization.app.commands.pos_terminal import (
    CreatePosTerminalCommandHandler,
    DeletePosTerminalCommandHandler,
    TerminalPlacement,
    UpdatePosTerminalCommandHandler,
)
from src.organization.app.numbering import DocumentNumbering
from src.organization.app.queries.branch import (
    GetAccessibleBranchesQueryHandler,
    GetAllBranchesQueryHandler,
    GetBranchByIdQueryHandler,
)
from src.organization.app.queries.emission_point import (
    GetAllEmissionPointsQueryHandler,
    GetEmissionPointByIdQueryHandler,
)
from src.organization.app.queries.pos_terminal import (
    GetAllPosTerminalsQueryHandler,
    GetBranchTerminalsQueryHandler,
    GetPosTerminalByIdQueryHandler,
)
from src.organization.infra.mappers import (
    BranchMapper,
    EmissionPointMapper,
    PosTerminalMapper,
)
from src.organization.infra.repositories import (
    SqlAlchemyBranchRepository,
    SqlAlchemyDocumentSequenceRepository,
    SqlAlchemyEmissionPointRepository,
    SqlAlchemyPosTerminalRepository,
)

INJECTABLES = [
    BranchMapper,
    EmissionPointMapper,
    PosTerminalMapper,
    SqlAlchemyBranchRepository,
    SqlAlchemyEmissionPointRepository,
    SqlAlchemyPosTerminalRepository,
    SqlAlchemyDocumentSequenceRepository,
    DocumentNumbering,
    CreateBranchCommandHandler,
    UpdateBranchCommandHandler,
    DeleteBranchCommandHandler,
    GetAllBranchesQueryHandler,
    GetBranchByIdQueryHandler,
    GetAccessibleBranchesQueryHandler,
    CreateEmissionPointCommandHandler,
    UpdateEmissionPointCommandHandler,
    DeleteEmissionPointCommandHandler,
    GetAllEmissionPointsQueryHandler,
    GetEmissionPointByIdQueryHandler,
    TerminalPlacement,
    CreatePosTerminalCommandHandler,
    UpdatePosTerminalCommandHandler,
    DeletePosTerminalCommandHandler,
    GetAllPosTerminalsQueryHandler,
    GetPosTerminalByIdQueryHandler,
    GetBranchTerminalsQueryHandler,
]
