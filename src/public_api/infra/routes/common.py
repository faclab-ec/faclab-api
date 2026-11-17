"""Shared pieces of the public routers (S6.3)."""

from typing import Any

from src.public_api.app.listing import Page
from src.shared.infra.validators import ErrorResponse, Meta

Responses = dict[int | str, dict[str, Any]]


def _error(description: str) -> dict[str, Any]:
    return {"description": description, "model": ErrorResponse}


_AUTH: Responses = {
    401: _error(
        "**Invalid credentials**: the token is missing, expired (`TOKEN_EXPIRED`) "
        "or no longer valid (`INVALID_TOKEN`: its client or secret was revoked, or "
        "the request comes from an address the client doesn't allow)."
    ),
    403: _error(
        "**Not allowed**: the token lacks the route's scope "
        "(`INSUFFICIENT_SCOPE`), is not an integration's (`PERMISSION_DENIED`) or "
        "names a branch the client may not operate in (`BRANCH_ACCESS_DENIED`)."
    ),
    422: _error("**Invalid request**: `VALIDATION_ERROR`, with the `field`."),
    429: _error(
        "**Rate limited** (`RATE_LIMITED`): retry after the seconds in `Retry-After`."
    ),
    503: _error("**Public API disabled** (`PUBLIC_API_DISABLED`)."),
}

READ: Responses = {**_AUTH, 400: _error("**Business rule violation**.")}
READ_ONE: Responses = {**READ, 404: _error("**Not found** (`NOT_FOUND`).")}
WRITE: Responses = {
    **READ_ONE,
    409: _error(
        "**Conflict**: a unique value is taken (`*_ALREADY_EXISTS`), the key of "
        "`Idempotency-Key` is still running (`IDEMPOTENCY_IN_PROGRESS`) or the "
        "state doesn't allow it."
    ),
}


def paginated(page: Page, meta: Meta):
    return meta.with_pagination(total=page.total, limit=page.limit, offset=page.offset)
