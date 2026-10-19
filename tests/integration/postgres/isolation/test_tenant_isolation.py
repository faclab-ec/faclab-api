"""No route of `main.app` shows or changes another tenant's data (S2.4).

Tenant A and tenant B have the same graph of rows (`dataset.py`); A calls every
route (`routes.py`) with B's ids. Each one must answer A exactly as for an id
that doesn't exist, A's listings must not change once B exists, and B's rows
must be the same at the end. Runs in order: the reads first, then the calls
that change A's data, then the check on B.
"""

import pytest
from fastapi.routing import APIRoute

from main import app
from tests.integration.postgres.isolation.dataset import MISSING
from tests.integration.postgres.isolation.harness import World, missing, tenant_rows
from tests.integration.postgres.isolation.routes import ROUTES, Route, keys, with_refs


def _app_routes() -> set[str]:
    return {
        f"{method} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def _not_a_bad_request(key: str, outcome) -> None:
    # A body the route rejects proves nothing about tenants: fix the body
    assert "VALIDATION_ERROR" not in outcome.codes, f"{key}: {outcome.text}"


def test_every_route_is_covered():
    missing_routes = _app_routes() - set(ROUTES)
    stale = set(ROUTES) - _app_routes()

    assert not missing_routes, f"add to isolation/routes.py: {sorted(missing_routes)}"
    assert not stale, f"no longer in main.app: {sorted(stale)}"


@pytest.mark.parametrize("key", keys("listing"))
def test_listings_are_the_same_once_another_tenant_exists(world: World, key: str):
    route = ROUTES[key]

    outcome = world.a.call(key, route, world.a.ids, query=False)

    assert outcome.ok, outcome.text
    assert not world.leaks(outcome), outcome.text
    assert outcome == world.listings[key]


@pytest.mark.parametrize("key", keys("foreign"))
def test_another_tenants_ids_look_missing(world: World, key: str):
    route: Route = ROUTES[key]
    foreign = {**world.a.ids, **{name: world.b.ids[name] for name in route.path}}
    absent = {
        **world.a.ids,
        **{name: missing(name, world.a.ids) for name in route.path},
    }

    seen = world.a.call(key, route, foreign)

    _not_a_bad_request(key, seen)
    assert not world.leaks(seen), seen.text
    assert seen == world.a.call(key, route, absent)
    if key.startswith("GET "):
        # The ids are real: their tenant reads them
        assert world.b.call(key, route, world.b.ids).ok


@pytest.mark.parametrize("key", with_refs())
def test_references_to_another_tenant_look_missing(world: World, key: str):
    route = ROUTES[key]
    seen_by_ref = {}
    for name in route.refs:
        foreign = {**world.a.ids, name: world.b.ids[name]}
        absent = {**world.a.ids, name: missing(name, world.a.ids)}

        seen = world.a.call(key, route, foreign)

        _not_a_bad_request(key, seen)
        assert not world.leaks(seen, sent=foreign[name]), seen.text
        assert seen == world.a.call(key, route, absent), name
        seen_by_ref[name] = seen

    # With A's own rows the call goes through: what fails is the reference
    own = world.a.call(key, route, world.a.ids)
    assert own.ok, own.text
    assert not world.leaks(own), own.text
    for name, seen in seen_by_ref.items():
        assert own != seen, f"{key}: {name} changes nothing"


@pytest.mark.parametrize("key", keys("creates"))
def test_what_a_tenant_creates_stays_in_it(world: World, key: str):
    route = ROUTES[key]
    assert route.created, f"{key}: name the GET that reads what it creates"

    created = world.a.call(key, route, world.a.ids)

    assert created.ok, created.text
    lookup = Route(path=("id",))
    read = f"GET {route.created.format('{id}')}"
    seen = world.b.call(read, lookup, {"id": created.data["id"]})
    assert seen == world.b.call(read, lookup, {"id": MISSING})


def test_the_other_tenant_is_untouched(world: World, pg_engine):
    assert tenant_rows(pg_engine, world.b.id) == world.b_rows
