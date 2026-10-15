import uuid
from datetime import UTC, datetime

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import trace
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
    "PERMISSION_DENIED": 403,
    "PASSWORD_CHANGE_REQUIRED": 403,
    "LOGIN_LOCKED": 429,
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


def _build_error_response(
    error_code: str,
    message: str,
    request_id: str,
    field: str | None = None,
    detail: str | None = None,
) -> dict:
    error = {"code": error_code, "message": message}
    if field is not None:
        error["field"] = field
    if detail is not None:
        error["detail"] = detail
    return {
        "errors": [error],
        "meta": _build_meta(request_id),
    }


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
    body = _build_error_response(
        error_code="HTTP_ERROR",
        message=str(exc.detail),
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        bind_vars = {"request_id": request_id}

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            bind_vars["trace_id"] = format(ctx.trace_id, "032x")
            bind_vars["span_id"] = format(ctx.span_id, "016x")

        structlog.contextvars.bind_contextvars(**bind_vars)

        try:
            response = await call_next(request)
            return response
        except BaseError as exc:
            status = _resolve_status(exc)
            logger.warning(
                "domain_error",
                error_code=exc.error_code,
                message=exc.message,
            )
            body = _build_error_response(
                error_code=exc.error_code,
                message=exc.message,
                request_id=request_id,
                detail=exc.detail,
            )
            return JSONResponse(status_code=status, content=body)
        except IntegrityError as exc:
            logger.warning("integrity_error", message=str(exc.orig))
            status, code, message = _integrity_error(exc)
            body = _build_error_response(
                error_code=code, message=message, request_id=request_id
            )
            return JSONResponse(status_code=status, content=body)
        except ValueError as exc:
            # The text of an unexpected ValueError is internal: only the log
            # gets it. Expected ones are InvalidValueError (a BaseError above)
            logger.warning("value_error", message=str(exc))
            body = _build_error_response(
                error_code="VALIDATION_ERROR",
                message="Invalid value",
                request_id=request_id,
            )
            return JSONResponse(status_code=422, content=body)
        except Exception as exc:
            logger.exception("unhandled_exception", error=str(exc))
            body = _build_error_response(
                error_code="INTERNAL_ERROR",
                message="Internal Server Error",
                request_id=request_id,
            )
            return JSONResponse(status_code=500, content=body)
        finally:
            structlog.contextvars.unbind_contextvars(
                "request_id", "trace_id", "span_id"
            )


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
    """Answers 413 when the request body is larger than `max_bytes`.

    A declared Content-Length is checked up front. A body without one
    (chunked) is read here up to the limit and then replayed to the app:
    FastAPI turns any error raised while it reads the body into a 400.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            if content_length.isdigit() and int(content_length) > self.max_bytes:
                await self._reject(scope, receive, send, headers)
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
            if size > self.max_bytes:
                await self._reject(scope, receive, send, headers)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, headers: Headers
    ) -> None:
        body = _build_error_response(
            error_code="REQUEST_TOO_LARGE",
            message=f"Request body exceeds {self.max_bytes} bytes",
            request_id=headers.get("x-request-id") or str(uuid.uuid4()),
        )
        await JSONResponse(status_code=413, content=body)(scope, receive, send)
