"""Guard test: the only routes without authentication are the ones declared here.

Health checks, login and refresh must stay public; any other route that loses
its require_permission/get_current_user dependency (or, for the routes of the
integrations, require_scope/get_principal) fails here.
"""

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from main import app
from src.auth.infra.dependencies import get_current_user, get_principal

HEALTH_ROUTES = {"GET /health/live", "GET /health/ready"}

PUBLIC_ROUTES = HEALTH_ROUTES | {
    # The public keys that verify the tokens (S6.1)
    "GET /.well-known/jwks.json",
    "POST /api/auth/login",
    # Authenticates itself with the login's selection token or an access token
    "POST /api/auth/select-tenant",
    "POST /api/auth/refresh",
    # Ends the session of the refresh token in the body
    "POST /api/auth/logout",
    # An integration client authenticates with its client_id and secret (S6.2)
    "POST /api/oauth/token",
    # Only registered when DOCS_ENABLED is on
    "GET /",
    "GET /docs",
    "GET /docs/admin",
    "GET /docs/pos",
    "GET /openapi/admin.json",
    "GET /openapi/pos.json",
}


def _tree_contains_call(dep: Dependant, target) -> bool:
    if dep.call is target:
        return True
    return any(_tree_contains_call(sub, target) for sub in dep.dependencies)


def _public_routes() -> set[str]:
    return {
        f"{method} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and not _tree_contains_call(route.dependant, get_current_user)
        and not _tree_contains_call(route.dependant, get_principal)
        for method in route.methods or []
    }


def test_only_declared_routes_are_public():
    undeclared = sorted(_public_routes() - PUBLIC_ROUTES)

    assert not undeclared, "Routes without authentication:\n  - " + "\n  - ".join(
        undeclared
    )


def test_health_routes_are_public():
    assert HEALTH_ROUTES.issubset(_public_routes())
