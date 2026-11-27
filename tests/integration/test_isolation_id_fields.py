"""Every id a route takes is tried with another tenant's value (S9.3).

The isolation suite (`tests/integration/postgres/isolation`) swaps for tenant
B's the ids it names in each route's `refs` and in `PROBES`. This test reads
the ids each route of `main.app` accepts in its body and query (fields that end
in `Id`/`Ids`) and fails on one the suite never sends with a swapped value, so
a new field doesn't slip through. It needs no database: the bodies are built
with ids whose values name their dataset key.
"""

import re
import typing
from typing import Any

from fastapi.routing import APIRoute
from pydantic import BaseModel

from main import app
from tests.integration.postgres.isolation.routes import PROBES, ROUTES

# Not references to a row: a tax identification is a value
_NOT_REFERENCES = {"tax_id", "taxId"}


def _models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [m for arg in typing.get_args(annotation) for m in _models(arg)]


def _model_ids(model: type[BaseModel], prefix: str, seen: frozenset) -> set[str]:
    if model in seen:
        return set()
    found = set()
    for name, field in model.model_fields.items():
        alias = field.serialization_alias or field.alias or name
        if name.endswith(("_id", "_ids")) and name not in _NOT_REFERENCES:
            found.add(prefix + alias)
        for nested in _models(field.annotation):
            found |= _model_ids(nested, f"{prefix}{alias}.", seen | {model})
    return found


def _dependants(dependant):
    yield dependant
    for sub in dependant.dependencies:
        yield from _dependants(sub)


def _id_fields(route: APIRoute) -> set[str]:
    found: set[str] = set()
    for dependant in _dependants(route.dependant):
        for param in dependant.body_params:
            for model in _models(param.field_info.annotation):
                found |= _model_ids(model, "body.", frozenset())
        for param in dependant.query_params:
            alias = param.alias
            if alias.endswith(("Id", "Ids")) and alias not in _NOT_REFERENCES:
                found.add("query." + alias)
    return found


class _Ids(dict):
    """A distinct value per dataset key, so a value names its key"""

    def __init__(self):
        super().__init__(marker="PRB", seed=7)

    def __missing__(self, key: str) -> int:
        self[key] = value = 900_000 + len(self)
        return value


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower()


def _values(data: Any, path: str) -> list[Any]:
    """What a body or query sends at a dotted path, lists flattened"""
    current = [data]
    for part in path.split("."):
        found = []
        for value in current:
            for item in value if isinstance(value, list) else [value]:
                if not isinstance(item, dict):
                    continue
                for key in (part, _camel(part), _snake(part)):
                    if key in item:
                        found.append(item[key])
                        break
        current = found
    flat: list[Any] = []
    for value in current:
        flat += value if isinstance(value, list) else [value]
    return flat


def _sent(body, query, ids: _Ids) -> dict[str, Any]:
    return {"body": body(ids) if body else {}, "query": query(ids) if query else {}}


def _tried(key: str, field: str) -> bool:
    where, path = field.split(".", 1)
    route = ROUTES[key]
    ids = _Ids()
    sent = _values(_sent(route.body, route.query, ids)[where], path)
    if sent and set(sent) <= {ids[name] for name in route.refs}:
        return True
    for probe in PROBES:
        if probe.key != key:
            continue
        ids = _Ids()
        sent = _values(
            _sent(probe.body or route.body, probe.query or route.query, ids)[where],
            path,
        )
        if ids[probe.name] in sent:
            return True
    return False


def test_every_id_a_route_takes_is_tried_with_another_tenants():
    untried = [
        f"{method} {route.path}: {field}"
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
        if f"{method} {route.path}" in ROUTES
        and not ROUTES[f"{method} {route.path}"].exempt
        for field in sorted(_id_fields(route))
        if not _tried(f"{method} {route.path}", field)
    ]

    assert not untried, (
        "send these ids from isolation/routes.py (refs or PROBES): "
        + "; ".join(untried)
    )


def test_every_probe_names_a_route():
    assert {probe.key for probe in PROBES} <= set(ROUTES)
