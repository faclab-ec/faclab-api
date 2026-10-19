from wireup import injectable

from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.organization.infra.models import (
    BranchModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class BranchMapper(Mapper[Branch, BranchModel]):
    __entity__ = Branch
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class EmissionPointMapper(Mapper[EmissionPoint, EmissionPointModel]):
    __entity__ = EmissionPoint
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class PosTerminalMapper(Mapper[PosTerminal, PosTerminalModel]):
    __entity__ = PosTerminal
    __exclude_fields__ = frozenset({"created_at"})
