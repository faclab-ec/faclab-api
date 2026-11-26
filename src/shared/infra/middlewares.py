import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
from pydantic.alias_generators import to_camel
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.shared.domain.exceptions import (
    ApplicationError,
    BaseError,
    ConflictError,
    DomainError,
    InvalidValueError,
)

logger = structlog.get_logger(__name__)

ERROR_CODE_TO_STATUS = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 422,
    "REQUEST_VALIDATION_ERROR": 422,
    "INVALID_CREDENTIALS": 401,
    "INVALID_TOKEN": 401,
    "TOKEN_EXPIRED": 401,
    "TOKEN_REUSED": 401,
    "TENANT_REQUIRED": 401,
    "PERMISSION_DENIED": 403,
    "PASSWORD_CHANGE_REQUIRED": 403,
    "NO_ACTIVE_TENANT": 403,
    "TENANT_ACCESS_DENIED": 403,
    "BRANCH_ACCESS_DENIED": 403,
    # An integration's token on the internal API, or without the scope (S6.2)
    "INTEGRATION_NOT_ALLOWED": 403,
    "INSUFFICIENT_SCOPE": 403,
    # A platform operator's token on a company's route (S8.5)
    "PLATFORM_NOT_ALLOWED": 403,
    "PLATFORM_CONSOLE_DISABLED": 503,
    # A subscription that isn't active leaves its tenant read-only (S8.4)
    "SUBSCRIPTION_READ_ONLY": 403,
    "INVALID_BRANCH_HEADER": 422,
    "INVALID_TERMINAL_HEADER": 422,
    "IDEMPOTENCY_KEY_REQUIRED": 422,
    "INVALID_IDEMPOTENCY_KEY": 422,
    "IDEMPOTENCY_KEY_REUSED": 422,
    "QUANTITY_PRECISION_EXCEEDED": 422,
    # A reference checked by a command, not by a foreign key (an integration
    # client's branches, S6.2); a foreign key's answers the same
    "REFERENCE_NOT_FOUND": 422,
    # A bulk import's file that can't be read as its template (S5.8)
    "IMPORT_FILE_INVALID": 422,
    # A webhook URL the server may not call (SSRF), or exclude_own_changes
    # without the endpoint's integration client (S6.4)
    "WEBHOOK_URL_NOT_ALLOWED": 422,
    "WEBHOOK_OWNER_REQUIRED": 422,
    "LOGIN_LOCKED": 429,
    # The public API (S6.3): over a rate limit, or turned off
    "RATE_LIMITED": 429,
    "PUBLIC_API_DISABLED": 503,
    "WEBHOOKS_DISABLED": 503,
    # The SMTP server refused or couldn't be reached (S5.4)
    "EMAIL_DELIVERY_FAILED": 502,
}

# Checked in order, so subclasses go before their bases
LAYER_TO_STATUS = {
    ConflictError: 409,
    DomainError: 400,
    ApplicationError: 400,
}

_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"


def _resolve_status(exc: BaseError) -> int:
    status = ERROR_CODE_TO_STATUS.get(exc.error_code)
    if status:
        return status
    for layer, code in LAYER_TO_STATUS.items():
        if isinstance(exc, layer):
            return code
    return 500


def _build_meta(request_id: str) -> dict:
    return {
        "requestId": request_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _database_error_fields(exc: IntegrityError) -> dict[str, str]:
    """What a log may say about a database error: its type, SQLSTATE and the
    name of the constraint, never the driver's message (it quotes values)."""
    fields = {"error_type": type(exc.orig).__name__}
    pgcode = getattr(exc.orig, "pgcode", None)
    if pgcode:
        fields["pgcode"] = pgcode
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint:
        fields["constraint"] = constraint
    return fields


def _integrity_error(exc: IntegrityError) -> tuple[int, str, str]:
    """Status, code and message for a database integrity error that no
    repository translated into a domain error."""
    pgcode = getattr(exc.orig, "pgcode", None)
    text = str(exc.orig)
    if pgcode == _UNIQUE_VIOLATION or "violates unique constraint" in text:
        return 409, "ALREADY_EXISTS", "A record with these values already exists"
    if pgcode == _FOREIGN_KEY_VIOLATION or "violates foreign key constraint" in text:
        if text.startswith("insert or update"):
            return 422, "REFERENCE_NOT_FOUND", "A referenced record does not exist"
        return (
            409,
            "RECORD_IN_USE",
            "Cannot complete operation because this record is referenced by other records",
        )
    return 409, "INTEGRITY_ERROR", "The operation violates a data integrity rule"


def build_error_response(
    error_code: str,
    message: str,
    request_id: str,
    field: str | None = None,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict:
    """The error envelope with one error. `extra` adds fields to its entry
    (snake_case keys, sent in camelCase)"""
    error: dict[str, Any] = {"code": error_code, "message": message}
    if field is not None:
        error["field"] = field
    if detail is not None:
        error["detail"] = detail
    for key, value in (extra or {}).items():
        error[to_camel(key)] = value
    return {
        "errors": [error],
        "meta": _build_meta(request_id),
    }


def public_error_code(request: Request, code: str, status: int) -> str:
    """The code the response gives: a path with its own error catalog (the
    public API, S6.3) translates the codes outside it. The translators are
    `app.state.error_translators`: path prefix -> f(code, status)"""
    translators = getattr(request.app.state, "error_translators", None) or {}
    for prefix, translate in translators.items():
        if request.url.path.startswith(prefix):
            return translate(code, status)
    return code


def _build_validation_error_response(
    exc: RequestValidationError,
    request_id: str,
) -> dict:
    errors = []
    for err in exc.errors():
        loc_parts = [str(p) for p in err.get("loc", [])]
        field = ".".join(loc_parts) if loc_parts else None
        errors.append(
            {
                "code": "VALIDATION_ERROR",
                "message": err.get("msg", "Validation error"),
                "field": field,
            }
        )
    return {
        "errors": errors,
        "meta": _build_meta(request_id),
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI handles request validation before the error middleware sees it, so
    register this with `app.add_exception_handler` to keep the error envelope."""
    # Only where and why: str(exc) includes each error's `input`, which can be
    # a password sent in the body
    logger.warning(
        "request_validation_error",
        errors=[
            {"loc": err.get("loc"), "type": err.get("type"), "msg": err.get("msg")}
            for err in exc.errors()
        ],
    )
    body = _build_validation_error_response(exc, _request_id(request))
    return JSONResponse(status_code=422, content=body)


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Wraps Starlette HTTP errors (unknown route, wrong method...) in the error
    envelope. Register with `app.add_exception_handler`."""
    logger.warning(
        "http_error",
        status_code=exc.status_code,
        detail=exc.detail,
    )
    body = build_error_response(
        error_code=public_error_code(request, "HTTP_ERROR", exc.status_code),
        message=str(exc.detail),
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


def _valid_request_id(value: str | None) -> str:
    """The client's X-Request-Id when it is a UUID, a new one otherwise: the id
    reaches logs and responses, so free text from outside never does."""
    if value:
        try:
            return str(uuid.UUID(value))
        except ValueError:
            pass
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Gives each request an id: `request.state.request_id`, `http.request.id`
    in its logs and span, and the `X-Request-Id` response header."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _valid_request_id(Headers(scope=scope).get("x-request-id"))
        scope.setdefault("state", {})["request_id"] = request_id
        trace.get_current_span().set_attribute("http.request.id", request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(**{"http.request.id": request_id}):
            await self.app(scope, receive, send_with_request_id)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = _request_id(request)
        try:
            response = await call_next(request)
            return response
        except BaseError as exc:
            # Expected outcome (4xx): a warning, and the request span keeps
            # its status; only the code is recorded to search by it
            status = _resolve_status(exc)
            trace.get_current_span().set_attribute("faclab.error.code", exc.error_code)
            # An InvalidValueError quotes the value that failed ("Invalid
            # email: …", "RUC must have 13 digits: …"): the client gets it, the
            # log only the code (S8.7)
            fields = (
                {} if isinstance(exc, InvalidValueError) else {"message": exc.message}
            )
            logger.warning("domain_error", error_code=exc.error_code, **fields)
            body = build_error_response(
                error_code=public_error_code(request, exc.error_code, status),
                message=exc.message,
                request_id=request_id,
                detail=exc.detail,
                extra=exc.extra,
            )
            return JSONResponse(status_code=status, content=body)
        except IntegrityError as exc:
            # Never the driver's text: a unique violation quotes the row's
            # key (`Key (tenant_id, tax_id)=(…)`), a cédula or an email
            logger.warning("integrity_error", **_database_error_fields(exc))
            status, code, message = _integrity_error(exc)
            body = build_error_response(
                error_code=public_error_code(request, code, status),
                message=message,
                request_id=request_id,
            )
            return JSONResponse(status_code=status, content=body)
        except ValueError as exc:
            # The text of an unexpected ValueError is internal: only the log
            # gets it. Expected ones are InvalidValueError (a BaseError above)
            # The text may quote the value that failed (S8.7): the type only
            logger.warning("value_error", error_type=type(exc).__name__)
            body = build_error_response(
                error_code="VALIDATION_ERROR",
                message="Invalid value",
                request_id=request_id,
            )
            return JSONResponse(status_code=422, content=body)
        except Exception as exc:
            # The traceback stays for debugging; the message is left out of the
            # event, and the span records the type alone (S8.7)
            logger.exception("unhandled_exception", error_type=type(exc).__name__)
            span = trace.get_current_span()
            span.add_event("exception", {"exception.type": type(exc).__qualname__})
            span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
            body = build_error_response(
                error_code="INTERNAL_ERROR",
                message="Internal Server Error",
                request_id=request_id,
            )
            return JSONResponse(status_code=500, content=body)


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class SecurityHeadersMiddleware:
    """Adds basic security headers to every HTTP response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Answers 413 when the request body is larger than `max_bytes`, or than
    the limit `limits` gives its path (the file of a bulk import).

    A declared Content-Length is checked up front. A body without one
    (chunked) is read here up to the limit and then replayed to the app:
    FastAPI turns any error raised while it reads the body into a 400.
    """

    def __init__(
        self, app: ASGIApp, max_bytes: int, limits: dict[str, int] | None = None
    ):
        self.app = app
        self.max_bytes = max_bytes
        self.limits = limits or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self.limits.get(scope["path"].rstrip("/"), self.max_bytes)
        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            if content_length.isdigit() and int(content_length) > max_bytes:
                await self._reject(scope, receive, send, headers, max_bytes)
                return
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > max_bytes:
                await self._reject(scope, receive, send, headers, max_bytes)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        headers: Headers,
        max_bytes: int,
    ) -> None:
        body = build_error_response(
            error_code="REQUEST_TOO_LARGE",
            message=f"Request body exceeds {max_bytes} bytes",
            request_id=scope.get("state", {}).get("request_id")
            or _valid_request_id(headers.get("x-request-id")),
        )
        await JSONResponse(status_code=413, content=body)(scope, receive, send)
