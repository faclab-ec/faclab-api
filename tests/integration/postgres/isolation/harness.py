"""How the isolation suite calls the app and compares what it answers."""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from httpx import Response
from sqlalchemy import Engine, text

from src.shared.infra.database import Base
from tests.integration.postgres.api import Api
from tests.integration.postgres.isolation.dataset import (
    MISSING,
    MISSING_TEXT,
    Ids,
    customer_tax_id,
    supplier_tax_id,
)
from tests.integration.postgres.isolation.routes import Route

MARKER_A = "AAA"
MARKER_B = "ZZB"

# Values that change between two identical calls
VOLATILE = {"generatedAt", "timestamp"}


@dataclass(frozen=True)
class Outcome:
    """What a call answered: the status and either the error codes or the data"""

    status: int
    codes: tuple[str, ...]
    data: Any
    text: str

    @classmethod
    def of(cls, response: Response) -> "Outcome":
        body = response.json() if response.content else None
        codes: tuple[str, ...] = ()
        data = None
        if isinstance(body, dict) and "errors" in body:
            codes = tuple(error["code"] for error in body["errors"])
        elif isinstance(body, dict):
            data = _stable(body.get("data", body))
        else:
            data = _stable(body)
        return cls(response.status_code, codes, data, response.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Outcome):
            return NotImplemented
        return (self.status, self.codes, self.data) == (
            other.status,
            other.codes,
            other.data,
        )

    def __hash__(self) -> int:
        return hash((self.status, self.codes))

    def __repr__(self) -> str:
        return f"Outcome({self.status}, {self.codes or self.data!r})"


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


@dataclass
class Tenant:
    id: UUID
    api: Api
    ids: Ids

    def call(self, key: str, route: Route, ids: Ids, query: bool = True) -> Outcome:
        """Calls the route as this tenant, with the path, body and query built
        from `ids` (this tenant's, or with some of another tenant's)"""
        method, template = key.split(" ", 1)
        values = iter(ids[name] for name in route.path)
        path = re.sub(r"\{[^}]+\}", lambda _: str(next(values)), template)
        kwargs: dict[str, Any] = {}
        if route.body:
            kwargs["json"] = route.body(ids)
        if route.query and query:
            kwargs["params"] = route.query(ids)
        response = self.api.client.request(
            method, path, headers=self.api.headers, **kwargs
        )
        return Outcome.of(response)


@dataclass
class World:
    a: Tenant
    b: Tenant
    # A's listings before B existed
    listings: dict[str, Outcome]
    # B's rows right after it was built, as the superuser sees them
    b_rows: dict[str, tuple]

    def leaks(self, outcome: Outcome, sent: object = None) -> list[str]:
        """B's markers in a response to A, but the value A sent (an error may
        repeat it)"""
        forbidden = (
            MARKER_B,
            MARKER_B.lower(),
            str(self.b.id),
            customer_tax_id(2),
            supplier_tax_id(2),
        )
        return [v for v in forbidden if v != sent and v in outcome.text]


def missing(name: str, ids: Ids) -> Any:
    return MISSING_TEXT if isinstance(ids[name], str) else MISSING


def tenant_rows(engine: Engine, tenant_id: UUID) -> dict[str, tuple]:
    """Count and hash of the tenant's rows in every table that has them, plus
    its members' users"""
    tables = [t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c]
    rows = {}
    with engine.connect() as conn:
        for table in tables:
            rows[table] = tuple(
                conn.execute(
                    text(
                        f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t.id), '')) FROM \"{table}\" t WHERE t.tenant_id = :tenant"
                    ),
                    {"tenant": tenant_id},
                ).one()
            )
        rows["users"] = tuple(
            conn.execute(
                text(
                    "SELECT count(*), md5(coalesce(string_agg(u::text, '|' ORDER BY u.id), ''))"
                    " FROM users u WHERE u.id IN"
                    " (SELECT user_id FROM memberships WHERE tenant_id = :tenant)"
                ),
                {"tenant": tenant_id},
            ).one()
        )
    return rows
