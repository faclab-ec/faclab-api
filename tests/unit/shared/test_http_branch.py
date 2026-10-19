"""`X-Branch-Id`: AuthMiddleware runs the request in that branch when the user
may enter it (claim `bids`), and every authenticated route rejects one it can't
use. With the API's real middleware order."""

from uuid import UUID

import structlog
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from opentelemetry.trace import SpanKind

import main
from src.auth.domain.entities import AuthenticatedUser, Role, User
from src.auth.infra.dependencies import get_current_user, require_branch
from src.auth.infra.token_service import JwtTokenService
from src.shared.domain.tenant import current_tenant
from src.shared.infra.adapters.telemetry import instrument_fastapi
from src.tenancy.domain.entities import Membership

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000b1")

logger = structlog.get_logger("tests.branch")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/context")
    def context(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
        tenant = current_tenant()
        logger.info("branch_route")
        return {"branch": tenant.branch_id if tenant else None}

    @app.get("/anonymous")
    def anonymous() -> dict:
        tenant = current_tenant()
        return {"branch": tenant.branch_id if tenant else None}

    @app.get("/branch-operation")
    def branch_operation(branch_id: int = Depends(require_branch)) -> dict:
        return {"branch": branch_id}

    main.add_middlewares(app)
    instrument_fastapi(app)
    return app


def _token(branch_ids: list[int] | None = None) -> str:
    user = User(id=5, username="caja", email="caja@test.local", password_hash="x")
    membership = Membership(tenant_id=TENANT_ID, user_id=5, role=Role.CASHIER)
    pair = JwtTokenService().issue_pair(
        user, membership, 1, "jti", branch_ids=branch_ids
    )
    return pair.access_token


def _headers(token: str, branch: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if branch is not None:
        headers["X-Branch-Id"] = branch
    return headers


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["errors"][0]["code"]


def test_without_the_header_the_request_has_no_branch():
    body = TestClient(_app()).get("/context", headers=_headers(_token())).json()

    assert body == {"branch": None}


def test_a_user_with_every_branch_runs_in_the_one_of_the_header():
    response = TestClient(_app()).get("/context", headers=_headers(_token(), "7"))

    assert response.json() == {"branch": 7}
    assert current_tenant() is None


def test_a_user_limited_to_some_branches_enters_one_of_them():
    token = _token(branch_ids=[1, 3])

    response = TestClient(_app()).get("/context", headers=_headers(token, "3"))

    assert response.json() == {"branch": 3}


def test_another_branch_is_forbidden_on_every_authenticated_route():
    client = TestClient(_app())
    headers = _headers(_token(branch_ids=[1]), "2")

    assert _error(client.get("/context", headers=headers)) == (
        403,
        "BRANCH_ACCESS_DENIED",
    )
    assert _error(client.get("/branch-operation", headers=headers)) == (
        403,
        "BRANCH_ACCESS_DENIED",
    )


def test_a_header_that_is_not_a_branch_id_is_rejected():
    client = TestClient(_app())

    for value in ("abc", "0", "-1", "1.5", "99999999999"):
        response = client.get("/context", headers=_headers(_token(), value))
        assert _error(response) == (422, "INVALID_BRANCH_HEADER"), value


def test_an_anonymous_request_ignores_the_header():
    response = TestClient(_app()).get("/anonymous", headers={"X-Branch-Id": "2"})

    assert response.json() == {"branch": None}


def test_a_branch_operation_needs_the_header():
    client = TestClient(_app())

    missing = client.get("/branch-operation", headers=_headers(_token()))
    given = client.get("/branch-operation", headers=_headers(_token(), "4"))

    assert _error(missing) == (400, "BRANCH_REQUIRED")
    assert given.json() == {"branch": 4}


def test_the_branch_operation_documents_the_header():
    operation = _app().openapi()["paths"]["/branch-operation"]["get"]

    assert {"name": "X-Branch-Id", "in": "header"}.items() <= next(
        p for p in operation["parameters"] if p["name"] == "X-Branch-Id"
    ).items()


def test_the_request_logs_and_span_carry_the_branch(span_exporter, json_logs):
    TestClient(_app()).get("/context", headers=_headers(_token(), "7"))

    lines = {line["event"]: line for line in json_logs()}
    assert lines["branch_route"]["faclab.branch.id"] == 7
    [server] = [
        s for s in span_exporter.get_finished_spans() if s.kind == SpanKind.SERVER
    ]
    assert (server.attributes or {}).get("faclab.branch.id") == 7
