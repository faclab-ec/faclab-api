"""AuthMiddleware runs each authenticated request in its token's tenant, with
the API's real middleware order."""

from uuid import UUID

import jwt
import structlog
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind

import main
from config import config
from src.auth.domain.entities import AuthenticatedUser, Role, User
from src.auth.infra.dependencies import get_current_user
from src.auth.infra.token_service import JwtTokenService
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.tenant import TenantSource, current_tenant
from src.shared.infra.adapters.telemetry import instrument_fastapi
from src.tenancy.domain.entities import Membership

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000a1")

logger = structlog.get_logger("tests.auth")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/tenant")
    def tenant() -> dict:
        context = current_tenant()
        logger.info("tenant_route")
        if context is None:
            return {"tenant": None}
        return {
            "tenant": str(context.tenant_id),
            "user": context.user_id,
            "source": context.source,
        }

    @app.get("/missing")
    def missing() -> dict:
        raise NotFoundError("Item not found")

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
        return {"id": user.id}

    main.add_middlewares(app)
    instrument_fastapi(app)
    return app


def _token(role: Role = Role.CASHIER) -> str:
    user = User(id=5, username="caja", email="caja@test.local", password_hash="x")
    membership = Membership(tenant_id=TENANT_ID, user_id=5, role=role)
    return JwtTokenService().issue_pair(user, membership, 1, "jti").access_token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_an_authenticated_request_runs_in_the_token_tenant():
    body = TestClient(_app()).get("/tenant", headers=_bearer(_token())).json()

    assert body == {"tenant": str(TENANT_ID), "user": 5, "source": TenantSource.REQUEST}
    assert current_tenant() is None


def test_an_anonymous_request_has_no_tenant():
    assert TestClient(_app()).get("/tenant").json() == {"tenant": None}


def test_the_request_logs_and_span_carry_the_tenant(span_exporter, json_logs):
    client = TestClient(_app())
    client.get("/tenant", headers=_bearer(_token()))
    client.get("/missing", headers=_bearer(_token()))

    lines = {line["event"]: line for line in json_logs()}
    assert lines["tenant_route"]["faclab.tenant.id"] == str(TENANT_ID)
    # Written by the error middleware, which runs inside the tenant too
    assert lines["domain_error"]["faclab.tenant.id"] == str(TENANT_ID)
    servers = [
        s for s in span_exporter.get_finished_spans() if s.kind == SpanKind.SERVER
    ]
    assert [(s.attributes or {}).get("faclab.tenant.id") for s in servers] == [
        str(TENANT_ID),
        str(TENANT_ID),
    ]


def test_a_token_with_an_unknown_role_is_invalid():
    claims = jwt.decode(_token(), options={"verify_signature": False})
    forged = jwt.encode({**claims, "role": 99}, config.JWT_SECRET, algorithm="HS256")

    response = TestClient(_app()).get("/me", headers=_bearer(forged))

    assert response.status_code == 401
    assert response.json()["errors"][0]["code"] == "INVALID_TOKEN"
