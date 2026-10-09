"""Guard test: every /api/pos route must carry a require_permission dependency.

Routes are read from the real application, so a router mounted in `main.py`
without authorization coverage fails here.
"""

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from main import app
from src.auth.infra.dependencies import get_current_user


def _tree_contains_call(dep: Dependant, target) -> bool:
    if dep.call is target:
        return True
    return any(_tree_contains_call(sub, target) for sub in dep.dependencies)


def _pos_routes() -> list[APIRoute]:
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api/pos")
    ]


def test_every_pos_route_requires_authenticated_user():
    unprotected: list[str] = []
    for route in _pos_routes():
        if not _tree_contains_call(route.dependant, get_current_user):
            for method in sorted(route.methods or []):
                unprotected.append(f"{method} {route.path}")
    assert not unprotected, (
        "POS routes missing require_permission/get_current_user:\n  - "
        + "\n  - ".join(unprotected)
    )


def test_pos_routes_exist():
    """Sanity check — the filter is actually finding routes."""
    assert len(_pos_routes()) > 0
