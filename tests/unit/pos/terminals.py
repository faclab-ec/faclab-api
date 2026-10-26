"""A terminal of branch 1 and the resolver that returns it, for the handlers
that run at a POS terminal"""

from unittest.mock import MagicMock

from src.organization.domain.entities import PosTerminal
from src.pos.terminal.app.resolver import TerminalRequest

BRANCH_ID = 1
LOCATION_ID = 7

TERMINAL = PosTerminal(
    id=3,
    branch_id=BRANCH_ID,
    emission_point_id=2,
    default_location_id=LOCATION_ID,
    code="CAJA-01",
    name="Caja 1",
)

AT_TERMINAL = TerminalRequest(branch_id=BRANCH_ID, terminal_id=3)


def terminal_resolver(terminal: PosTerminal = TERMINAL) -> MagicMock:
    resolver = MagicMock()
    resolver.terminal.return_value = terminal
    return resolver


def numbering(number: str = "V-001-000001") -> MagicMock:
    service = MagicMock()
    service.next.return_value = number
    return service
