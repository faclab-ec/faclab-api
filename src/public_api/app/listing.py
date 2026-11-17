"""Listings of the public API (S6.3, G-73): one page in a stable order.

Every listing ends its order with the id, so a page never repeats nor skips
rows of the previous one. `sort` takes one field of a list each resource
allows (`name`, `-updatedAt`); with `updatedSince` and without `sort` the
order is `updatedAt, id`, the one a sync walks.

These are read models: like the reports, they query the SQLAlchemy models from
the application layer, each with `tenant_criteria` for every model it reads.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql import Select

from src.public_api.domain.exceptions import InvalidSortError

# The page size integrations get without `limit`, and the most they can ask for
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

Column = InstrumentedAttribute[Any]


@dataclass(frozen=True)
class PageRequest:
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    sort: str | None = None
    updated_since: datetime | None = None


@dataclass(frozen=True)
class Page:
    items: list[Any]
    total: int
    limit: int
    offset: int


def ordering(
    page: PageRequest,
    fields: Mapping[str, Column],
    id_column: Column,
) -> list[Any]:
    """The ORDER BY of `page.sort` among `fields` (public name -> column), the
    id last in the same direction. Without `sort`: `updatedAt` when the page
    syncs (`updatedSince`) and the resource has it, else the id."""
    sort = page.sort
    if sort is None and page.updated_since is not None and "updatedAt" in fields:
        sort = "updatedAt"
    if sort is None:
        return [asc(id_column)]
    name = sort.removeprefix("-")
    column = fields.get(name)
    if column is None:
        raise InvalidSortError(sort, sorted(fields))
    direction = desc if sort.startswith("-") else asc
    if column is id_column:
        return [direction(id_column)]
    return [direction(column), direction(id_column)]


def paginate(
    session: Session, statement: Select, order_by: Sequence[Any], page: PageRequest
) -> Page:
    """One page of `statement` in `order_by`, with the total of its rows"""
    total = session.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    )
    rows = session.execute(
        statement.order_by(*order_by).limit(page.limit).offset(page.offset)
    )
    items = list(rows.scalars()) if _one_entity(statement) else list(rows)
    return Page(items=items, total=total or 0, limit=page.limit, offset=page.offset)


def _one_entity(statement: Select) -> bool:
    return len(statement.column_descriptions) == 1


def columns_of(model: Any) -> dict[str, Any]:
    """A row of a model as a dict of its columns"""
    return {
        attr.key: getattr(model, attr.key) for attr in model.__mapper__.column_attrs
    }
