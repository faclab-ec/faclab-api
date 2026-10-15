import asyncio
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import main  # configures logging at import, so caplog's handler comes after it
from src.auth.domain.entities import Role, User
from src.auth.infra.token_service import JwtTokenService
from src.shared.infra.middlewares import (
    BodySizeLimitMiddleware,
    ErrorHandlingMiddleware,
    SecurityHeadersMiddleware,
)


def _access_token() -> str:
    user = User(
        id=1,
        username="ana",
        email="ana@example.com",
        password_hash="h",
        role=Role.ADMIN,
    )
    return JwtTokenService().issue_pair(user, 1, "jti").access_token


def test_a_short_new_password_does_not_reach_the_log(caplog):
    secret = "Sh0rtPw"
    with caplog.at_level(logging.DEBUG):
        response = TestClient(main.app).post(
            "/api/auth/change-password",
            json={"currentPassword": "whatever-1", "newPassword": secret},
            headers={"Authorization": f"Bearer {_access_token()}"},
        )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.newPassword"
    logged = [str(record.msg) for record in caplog.records]
    assert any("request_validation_error" in line for line in logged)
    assert not any(secret in line for line in logged)


def test_responses_carry_security_headers():
    response = TestClient(main.app).get("/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


# Body size limit


def _limited_app(max_bytes: int = 10):
    class Body(BaseModel):
        text: str

    app = FastAPI()

    @app.post("/echo")
    def echo(body: Body) -> dict:
        return {"text": body.text}

    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _send(app, chunks: list[bytes], content_length: int | None):
    """Raw ASGI request, so the body can arrive in chunks without a length."""
    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/echo",
        "raw_path": b"/echo",
        "query_string": b"",
        "headers": headers,
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1234),
        "root_path": "",
    }
    pending = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return start["status"], json.loads(body), dict(start["headers"])


def test_a_declared_body_over_the_limit_gets_413():
    payload = json.dumps({"text": "far too long"}).encode()

    status, body, headers = _send(_limited_app(), [payload], len(payload))

    assert status == 413
    assert body["errors"][0]["code"] == "REQUEST_TOO_LARGE"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_a_chunked_body_over_the_limit_gets_413():
    status, body, _ = _send(_limited_app(), [b'{"text": ', b'"far too long"}'], None)

    assert status == 413
    assert body["errors"][0]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.parametrize("content_length", [True, False], ids=["declared", "chunked"])
def test_a_body_within_the_limit_reaches_the_app(content_length):
    chunks = [b'{"text"', b': "ok"}']
    size = sum(len(c) for c in chunks) if content_length else None

    status, body, _ = _send(_limited_app(max_bytes=100), chunks, size)

    assert status == 200
    assert body == {"text": "ok"}
