import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import IntegrityError

from src.shared.infra.middlewares import ErrorHandlingMiddleware


def _make_middleware():
    app = MagicMock()
    return ErrorHandlingMiddleware(app)


def _make_request():
    req = MagicMock()
    req.headers = {}
    req.state = MagicMock()
    return req


def _dispatch(exc: Exception) -> tuple[int, dict]:
    middleware = _make_middleware()
    response = asyncio.run(
        middleware.dispatch(_make_request(), AsyncMock(side_effect=exc))
    )
    return response.status_code, json.loads(response.body)


def _integrity_error(message: str, pgcode: str | None = None) -> IntegrityError:
    orig = Exception(message)
    orig.pgcode = pgcode  # ty: ignore[unresolved-attribute]
    return IntegrityError(statement="...", params={}, orig=orig)


def test_deleting_a_referenced_record_returns_409():
    status, body = _dispatch(
        _integrity_error(
            'update or delete on table "units_of_measure" violates foreign key '
            'constraint "products_unit_of_measure_id_fkey" on table "products"'
        )
    )

    assert status == 409
    assert body["errors"][0]["code"] == "RECORD_IN_USE"
    assert "referenced by other records" in body["errors"][0]["message"]
    assert "requestId" in body["meta"]
    assert "timestamp" in body["meta"]


def test_referencing_a_missing_record_returns_422():
    status, body = _dispatch(
        _integrity_error(
            'insert or update on table "movements" violates foreign key '
            'constraint "movements_product_id_fkey"',
            pgcode="23503",
        )
    )

    assert status == 422
    assert body["errors"][0]["code"] == "REFERENCE_NOT_FOUND"


def test_untranslated_unique_violation_returns_409():
    status, body = _dispatch(
        _integrity_error(
            'duplicate key value violates unique constraint "uq_stock_product_location"',
            pgcode="23505",
        )
    )

    assert status == 409
    assert body["errors"][0]["code"] == "ALREADY_EXISTS"
    # Database internals never reach the client
    assert "uq_stock" not in json.dumps(body)


def test_conflict_errors_return_409_with_their_code():
    from src.catalog.product.domain.exceptions import ProductSkuAlreadyExistsError

    status, body = _dispatch(ProductSkuAlreadyExistsError())

    assert status == 409
    assert body["errors"][0]["code"] == "PRODUCT_SKU_ALREADY_EXISTS"


def test_domain_error_detail_is_included():
    from src.sales.domain.exceptions import InvalidSaleStatusError

    status, body = _dispatch(InvalidSaleStatusError("CONFIRMED", "confirm"))

    assert status == 400
    assert body["errors"][0]["code"] == "INVALID_SALE_STATUS"
    assert body["errors"][0]["detail"] == "current_status=CONFIRMED, operation=confirm"


def _envelope_app():
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from pydantic import BaseModel
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from src.shared.infra.middlewares import (
        http_exception_handler,
        request_validation_exception_handler,
    )

    class Body(BaseModel):
        quantity: int

    app = FastAPI()

    @app.post("/items")
    def create_item(body: Body) -> dict:
        return {"quantity": body.quantity}

    app.add_exception_handler(
        RequestValidationError,
        request_validation_exception_handler,  # ty: ignore[invalid-argument-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,  # ty: ignore[invalid-argument-type]
    )
    app.add_middleware(ErrorHandlingMiddleware)
    return app


def _call(app, method: str, path: str, body: dict | None = None, headers=None):
    """Minimal ASGI request, so the test doesn't need an HTTP client package."""
    payload = json.dumps(body).encode() if body is not None else b""
    raw_headers = [(b"content-type", b"application/json")]
    raw_headers += [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1234),
        "root_path": "",
    }
    sent: list[dict] = []
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    content = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return start["status"], json.loads(content)


def test_request_validation_error_uses_envelope():
    status, body = _call(
        _envelope_app(),
        "POST",
        "/items",
        body={"quantity": "abc"},
        headers={"x-request-id": "req-1"},
    )

    assert status == 422
    assert "detail" not in body
    assert body["errors"][0]["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["field"] == "body.quantity"
    assert body["meta"]["requestId"] == "req-1"


def test_unknown_route_uses_envelope():
    status, body = _call(_envelope_app(), "GET", "/missing")

    assert status == 404
    assert body["errors"][0]["code"] == "HTTP_ERROR"
    assert "requestId" in body["meta"]


def test_unexpected_value_error_text_stays_out_of_the_response():
    status, body = _dispatch(ValueError("invalid literal for int() with base 10: 'x'"))

    assert status == 422
    assert body["errors"][0] == {"code": "VALIDATION_ERROR", "message": "Invalid value"}


def test_invalid_value_errors_keep_their_message():
    from src.shared.domain.value_objects import Email

    try:
        Email("not-an-email")
    except ValueError as exc:
        status, body = _dispatch(exc)

    assert status == 422
    assert body["errors"][0]["code"] == "VALIDATION_ERROR"
    assert body["errors"][0]["message"] == "Invalid email: not-an-email"


def test_new_auth_codes_map_to_their_status():
    from src.auth.domain.exceptions import LoginLockedError, TokenReusedError

    assert _dispatch(LoginLockedError())[0] == 429
    assert _dispatch(TokenReusedError())[0] == 401
