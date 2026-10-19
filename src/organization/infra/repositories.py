from sqlalchemy.orm import Session
from wireup import injectable

from src.organization.app.repositories import (
    BranchRepository,
    EmissionPointRepository,
    PosTerminalRepository,
)
from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.organization.domain.exceptions import (
    BranchEstablishmentCodeAlreadyExistsError,
    EmissionPointCodeAlreadyExistsError,
    MainBranchAlreadyExistsError,
    PosTerminalCodeAlreadyExistsError,
)
from src.organization.infra.mappers import (
    BranchMapper,
    EmissionPointMapper,
    PosTerminalMapper,
)
from src.organization.infra.models import (
    BranchModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=BranchRepository)
class SqlAlchemyBranchRepository(SqlAlchemyRepository[Branch], BranchRepository):
    __model__ = BranchModel
    __unique_errors__ = {
        "uq_branches_tenant_establishment_code": (
            BranchEstablishmentCodeAlreadyExistsError
        ),
        "uq_branches_tenant_main": MainBranchAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: BranchMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=EmissionPointRepository)
class SqlAlchemyEmissionPointRepository(
    SqlAlchemyRepository[EmissionPoint], EmissionPointRepository
):
    __model__ = EmissionPointModel
    __unique_errors__ = {
        "uq_emission_points_tenant_branch_code": EmissionPointCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: EmissionPointMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=PosTerminalRepository)
class SqlAlchemyPosTerminalRepository(
    SqlAlchemyRepository[PosTerminal], PosTerminalRepository
):
    __model__ = PosTerminalModel
    __unique_errors__ = {
        "uq_pos_terminals_tenant_branch_code": PosTerminalCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: PosTerminalMapper):
        super().__init__(session, mapper)
