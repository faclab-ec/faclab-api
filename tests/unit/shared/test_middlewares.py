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


def test_integrity_error_returns_409():
    middleware = _make_middleware()
    fake_request = _make_request()
    call_next = AsyncMock(
        side_effect=IntegrityError(
            statement="DELETE FROM units_of_measure WHERE id = 8",
            params={"id": 8},
            orig=Exception(
                'update or delete on table "units_of_measure" violates foreign key '
                'constraint "products_unit_of_measure_id_fkey" on table "products"'
            ),
        )
    )

    response = asyncio.get_event_loop().run_until_complete(
        middleware.dispatch(fake_request, call_next)
    )

    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["errors"][0]["code"] == "INTEGRITY_ERROR"
    assert "referenced by other records" in body["errors"][0]["message"]
    assert "requestId" in body["meta"]
    assert "timestamp" in body["meta"]


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
