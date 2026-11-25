"""Guard test: every /api/platform route but the login needs a platform operator
(S8.5), and no route of a company accepts the operator's token."""

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from main import app
from src.auth.infra.dependencies import get_platform_principal

LOGIN = "/api/platform/auth/login"


def _tree_contains_call(dep: Dependant, target) -> bool:
    if dep.call is target:
        return True
    return any(_tree_contains_call(sub, target) for sub in dep.dependencies)


def _platform_routes() -> list[APIRoute]:
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/platform")
    ]


def test_every_platform_route_requires_an_operator():
    unprotected = [
        f"{method} {route.path}"
        for route in _platform_routes()
        if route.path != LOGIN
        and not _tree_contains_call(route.dependant, get_platform_principal)
        for method in sorted(route.methods or [])
    ]
    assert not unprotected, "\n  - ".join(
        ["Platform routes without an operator:", *unprotected]
    )


def test_platform_routes_exist():
    assert len(_platform_routes()) > 1
