from src.pos.terminal.app.guard import PosBranchGuard
from src.pos.terminal.app.resolver import TerminalResolver
from src.pos.terminal.app.stock import TerminalStock

POS_TERMINAL_INJECTABLES = [
    TerminalResolver,
    PosBranchGuard,
    TerminalStock,
]
