"""Guard test: every route of the public API (/api/v1, S6.3) declares the
scopes it requires and the switch that turns the API off. Read from the real
application, so a public router mounted without them fails here."""

from uuid import uuid4

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from main import app
from src.auth.domain.entities import AuthenticatedUser, Role
from src.auth.domain.exceptions import InsufficientScopeError, PermissionDeniedError
from src.auth.domain.permissions import permissions_for
from src.auth.domain.principals import IntegrationPrincipal
from src.auth.domain.scopes import Scope
from src.public_api.infra.dependencies import RequireScope, public_api_enabled


def _calls(dep: Dependant) -> list:
    return [dep.call, *(call for sub in dep.dependencies for call in _calls(sub))]


def _public_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]


def test_public_routes_exist():
    assert len(_public_routes()) > 0


@pytest.mark.parametrize(
    "route", _public_routes(), ids=lambda r: f"{sorted(r.methods)[0]} {r.path}"
)
def test_every_public_route_requires_scopes_and_the_switch(route):
    calls = _calls(route.dependant)

    assert any(isinstance(call, RequireScope) for call in calls)
    assert public_api_enabled in calls


def test_only_branches_takes_any_scope():
    unscoped = {
        route.path
        for route in _public_routes()
        for call in _calls(route.dependant)
        if isinstance(call, RequireScope) and not call.scopes
    }

    assert unscoped == {"/api/v1/branches"}


def test_a_users_token_is_refused():
    user = AuthenticatedUser(
        id=1,
        username="admin",
        role=Role.ADMIN,
        tenant_id=uuid4(),
        permissions=permissions_for(Role.ADMIN),
    )

    with pytest.raises(PermissionDeniedError):
        RequireScope(Scope.PRODUCTS_READ)(principal=user)


def test_a_client_needs_the_scope():
    client = IntegrationPrincipal(
        client_id=1,
        public_id="fl_test_0123456789ab",
        name="Tienda web",
        tenant_id=uuid4(),
        scopes=frozenset({Scope.STOCK_READ}),
    )

    assert RequireScope(Scope.STOCK_READ)(principal=client) is client
    assert RequireScope()(principal=client) is client
    with pytest.raises(InsufficientScopeError):
        RequireScope(Scope.SALES_WRITE)(principal=client)
