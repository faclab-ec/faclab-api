"""An integration client's access token through the real `AuthMiddleware`
(S6.2): the routes of the frontend reject it, a route with `require_scope`
takes it only with the scope, and a client limited to a branch can't operate
in another one. The client's state comes from a fake `IntegrationAccess`."""

from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.app.services.integration_access import IntegrationAccess
from src.auth.app.services.token_service import ClientTokenClaims
from src.auth.domain.entities import AuthenticatedUser, Role, User
from src.auth.domain.permissions import Permission
from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.auth.infra.dependencies import (
    get_current_user,
    require_branch,
    require_permission,
    require_scope,
)
from src.auth.infra.middleware import AuthMiddleware
from src.shared.domain.tenant import current_tenant
from src.shared.infra.middlewares import ErrorHandlingMiddleware
from src.tenancy.domain.entities import Membership
from tests.tokens import token_service

TENANT_ID = UUID("00000000-0000-4000-8000-0000000000c1")
CLIENT = "fl_test_0123456789ab"


class FakeAccess(IntegrationAccess):
    """The client as it is now: active unless `revoked`, with `scopes` (None:
    the token's)"""

    def __init__(self):
        self.revoked = False
        self.scopes: frozenset[Scope] | None = None
        self.recorded: list[tuple[str, int]] = []

    def principal(self, claims: ClientTokenClaims, ip: str | None):
        if self.revoked:
            return None
        scopes = claims.scopes if self.scopes is None else claims.scopes & self.scopes
        return IntegrationPrincipal(
            client_id=9,
            public_id=claims.public_id,
            name="Tienda web",
            tenant_id=claims.tid,
            scopes=scopes,
            branch_ids=claims.bids,
        )

    def record_request(self, principal, status_code, ip):
        self.recorded.append((principal.public_id, status_code))


def _app(access: IntegrationAccess | None) -> FastAPI:
    app = FastAPI()

    @app.post("/public/sales")
    def create_sale(
        integration: IntegrationPrincipal = Depends(require_scope(Scope.SALES_WRITE)),
    ) -> dict:
        tenant = current_tenant()
        assert tenant is not None
        return {
            "client": integration.public_id,
            "user_id": tenant.user_id,
            "actor": tenant.user_name,
            "integration_id": tenant.integration_id,
        }

    @app.post("/public/branch-sales")
    def create_branch_sale(
        _: IntegrationPrincipal = Depends(require_scope(Scope.SALES_WRITE)),
        branch_id: int = Depends(require_branch),
    ) -> dict:
        return {"branch": branch_id}

    @app.get("/internal/products")
    def internal(user: AuthenticatedUser = Depends(get_current_user)) -> dict:
        return {"user": user.id}

    @app.post(
        "/internal/sales",
        dependencies=[Depends(require_permission(Permission.SALE_WRITE))],
    )
    def internal_sale() -> dict:
        return {}

    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(
        AuthMiddleware, token_service=token_service(), integrations=access
    )
    return app


def _token(scopes, branch_ids=None) -> str:
    return (
        token_service()
        .issue_client_access(
            public_id=CLIENT,
            tenant_id=TENANT_ID,
            secret_id=1,
            scopes=scopes,
            branch_ids=branch_ids,
        )
        .access_token
    )


def _headers(token: str, branch: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if branch is not None:
        headers["X-Branch-Id"] = branch
    return headers


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["errors"][0]["code"]


def test_without_sales_write_creating_a_sale_is_forbidden():
    client = TestClient(_app(FakeAccess()))

    response = client.post(
        "/public/sales", headers=_headers(_token({Scope.STOCK_READ, Scope.SALES_READ}))
    )

    assert _error(response) == (403, "INSUFFICIENT_SCOPE")


def test_with_sales_write_the_route_runs_as_the_integration():
    access = FakeAccess()
    client = TestClient(_app(access))

    response = client.post(
        "/public/sales", headers=_headers(_token({Scope.SALES_WRITE}))
    )

    assert response.status_code == 200
    # No user: the actor of the audit log is the client
    assert response.json() == {
        "client": CLIENT,
        "user_id": None,
        "actor": "Tienda web",
        "integration_id": 9,
    }
    assert current_tenant() is None
    assert access.recorded == [(CLIENT, 200)]


def test_a_scope_taken_from_the_client_stops_working_before_the_token_expires():
    access = FakeAccess()
    access.scopes = frozenset({Scope.STOCK_READ})
    client = TestClient(_app(access))

    response = client.post(
        "/public/sales", headers=_headers(_token({Scope.SALES_WRITE}))
    )

    assert _error(response) == (403, "INSUFFICIENT_SCOPE")


def test_a_client_limited_to_a_branch_operates_in_it():
    client = TestClient(_app(FakeAccess()))
    token = _token({Scope.SALES_WRITE}, branch_ids=[12])

    response = client.post("/public/branch-sales", headers=_headers(token, "12"))

    assert response.json() == {"branch": 12}


def test_a_client_limited_to_a_branch_cant_operate_in_another():
    access = FakeAccess()
    client = TestClient(_app(access))
    token = _token({Scope.SALES_WRITE}, branch_ids=[12])

    response = client.post("/public/branch-sales", headers=_headers(token, "15"))

    assert _error(response) == (403, "BRANCH_ACCESS_DENIED")
    # The error counts in its usage
    assert access.recorded == [(CLIENT, 403)]


def test_the_routes_of_the_frontend_reject_an_integration():
    client = TestClient(_app(FakeAccess()))
    token = _token(set(Scope))

    assert _error(client.get("/internal/products", headers=_headers(token))) == (
        403,
        "INTEGRATION_NOT_ALLOWED",
    )
    assert _error(client.post("/internal/sales", headers=_headers(token))) == (
        403,
        "INTEGRATION_NOT_ALLOWED",
    )


def test_a_revoked_client_token_is_invalid():
    access = FakeAccess()
    access.revoked = True
    client = TestClient(_app(access))

    response = client.post(
        "/public/sales", headers=_headers(_token({Scope.SALES_WRITE}))
    )

    assert _error(response) == (401, "INVALID_TOKEN")
    assert access.recorded == []


def test_with_integrations_disabled_every_client_token_is_invalid():
    client = TestClient(_app(None))

    response = client.post(
        "/public/sales", headers=_headers(_token({Scope.SALES_WRITE}))
    )

    assert _error(response) == (401, "INVALID_TOKEN")


def test_a_failing_state_lookup_rejects_the_token():
    class Broken(FakeAccess):
        def principal(self, claims, ip):
            raise RuntimeError("database down")

    response = TestClient(_app(Broken())).post(
        "/public/sales", headers=_headers(_token({Scope.SALES_WRITE}))
    )

    assert _error(response) == (401, "INVALID_TOKEN")


def test_a_user_token_is_not_an_integration():
    user = User(id=5, username="ana", email="ana@test.local", password_hash="x")
    membership = Membership(tenant_id=TENANT_ID, user_id=5, role=Role.ADMIN)
    token = token_service().issue_pair(user, membership, 1, "jti").access_token
    client = TestClient(_app(FakeAccess()))

    assert _error(client.post("/public/sales", headers=_headers(token))) == (
        403,
        "PERMISSION_DENIED",
    )
    assert client.get("/internal/products", headers=_headers(token)).json() == {
        "user": 5
    }
