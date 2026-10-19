"""The POS headers over HTTP, with the API's real middleware order:
`X-Terminal-Id` names the terminal of an operation that starts there and
`X-Branch-Id` the branch of one on an existing sale, shift or refund. Without
them only the local fallback (`POS_TERMINAL_FALLBACK`) answers."""

from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import main
from config import config
from src.auth.domain.entities import Role, User
from src.auth.infra.token_service import JwtTokenService
from src.pos.terminal.app.resolver import TerminalRequest
from src.pos.terminal.infra.dependencies import pos_branch, pos_terminal
from src.tenancy.domain.entities import Membership

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000b2")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/at-terminal")
    def at_terminal(terminal: TerminalRequest = Depends(pos_terminal)) -> dict:
        return {
            "branch": terminal.branch_id,
            "terminal": terminal.terminal_id,
            "allowed": sorted(terminal.allowed_branches or []),
        }

    @app.get("/in-branch")
    def in_branch(branch: TerminalRequest = Depends(pos_branch)) -> dict:
        return {"branch": branch.branch_id}

    main.add_middlewares(app)
    return app


def _headers(branch: str | None = None, terminal: str | None = None) -> dict:
    user = User(id=5, username="caja", email="caja@test.local", password_hash="x")
    membership = Membership(tenant_id=TENANT_ID, user_id=5, role=Role.CASHIER)
    token = (
        JwtTokenService()
        .issue_pair(user, membership, 1, "jti", branch_ids=[1, 2])
        .access_token
    )
    headers = {"Authorization": f"Bearer {token}"}
    if branch is not None:
        headers["X-Branch-Id"] = branch
    if terminal is not None:
        headers["X-Terminal-Id"] = terminal
    return headers


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["errors"][0]["code"]


@pytest.fixture
def fallback(monkeypatch):
    monkeypatch.setattr(config, "POS_TERMINAL_FALLBACK", True)


def test_an_operation_at_a_terminal_reads_both_headers():
    response = TestClient(_app()).get("/at-terminal", headers=_headers("2", "9"))

    assert response.json() == {"branch": 2, "terminal": 9, "allowed": [1, 2]}


def test_an_operation_at_a_terminal_needs_it():
    client = TestClient(_app())

    assert _error(client.get("/at-terminal", headers=_headers("2"))) == (
        400,
        "TERMINAL_REQUIRED",
    )
    assert _error(client.get("/at-terminal", headers=_headers(terminal="9"))) == (
        400,
        "BRANCH_REQUIRED",
    )


def test_a_header_that_is_not_a_terminal_id_is_rejected():
    client = TestClient(_app())

    for value in ("abc", "0", "-1", "1.5", "99999999999"):
        response = client.get("/at-terminal", headers=_headers("1", value))
        assert _error(response) == (422, "INVALID_TERMINAL_HEADER"), value


def test_the_branch_header_is_still_checked_against_the_users_branches():
    response = TestClient(_app()).get("/at-terminal", headers=_headers("3", "9"))

    assert _error(response) == (403, "BRANCH_ACCESS_DENIED")


def test_an_operation_in_a_branch_needs_it():
    client = TestClient(_app())

    assert _error(client.get("/in-branch", headers=_headers())) == (
        400,
        "BRANCH_REQUIRED",
    )
    assert client.get("/in-branch", headers=_headers("1")).json() == {"branch": 1}


def test_the_fallback_lets_the_resolver_pick(fallback):
    client = TestClient(_app())

    at_terminal = client.get("/at-terminal", headers=_headers()).json()
    in_branch = client.get("/in-branch", headers=_headers()).json()

    assert at_terminal == {"branch": None, "terminal": None, "allowed": [1, 2]}
    assert in_branch == {"branch": None}


def test_the_operations_document_the_headers():
    paths = _app().openapi()["paths"]

    at_terminal = {p["name"] for p in paths["/at-terminal"]["get"]["parameters"]}
    in_branch = {p["name"] for p in paths["/in-branch"]["get"]["parameters"]}

    assert {"X-Branch-Id", "X-Terminal-Id"} <= at_terminal
    assert "X-Branch-Id" in in_branch
