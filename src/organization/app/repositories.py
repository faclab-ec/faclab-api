from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.shared.app.repositories import Repository


class BranchRepository(Repository[Branch]):
    pass


class EmissionPointRepository(Repository[EmissionPoint]):
    pass


class PosTerminalRepository(Repository[PosTerminal]):
    pass
