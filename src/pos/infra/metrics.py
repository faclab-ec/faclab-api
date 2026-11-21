"""Sales metrics (S7.1). The POS composes sales, and every sale, also an API
one, is confirmed by its checkout, so they live here.

What happened is counted after the commit by `event_handlers.py`; what failed,
by `sale_attempt` around the handlers that confirm a sale.
"""

from collections.abc import Generator
from contextlib import contextmanager

from src.inventory.movement.infra.metrics import (
    INSUFFICIENT_STOCK,
    count_stock_rejection,
)
from src.shared.domain.exceptions import BaseError
from src.shared.infra.telemetry_instruments import sales_failed

# What the error middleware answers for an unexpected exception
UNEXPECTED_ERROR_CODE = "INTERNAL_ERROR"


@contextmanager
def sale_attempt(source: str) -> Generator[None]:
    """A sale that could not be confirmed (quick sale, confirm, API sale), by
    its error code. Its INSUFFICIENT_STOCK is also a stock rejection: a sale
    takes its stock with `TerminalStock.take`, not with a movement's handler.
    Around the handler inside `respond()`, so an idempotent replay counts
    nothing."""
    try:
        yield
    except BaseError as exc:
        sales_failed.add(
            1, {"error.code": exc.error_code, "faclab.sale.source": source}
        )
        if exc.error_code == INSUFFICIENT_STOCK:
            count_stock_rejection("sale")
        raise
    except Exception:
        sales_failed.add(
            1, {"error.code": UNEXPECTED_ERROR_CODE, "faclab.sale.source": source}
        )
        raise
