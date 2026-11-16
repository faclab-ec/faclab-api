from collections.abc import Iterable, Iterator
from itertools import islice
from typing import TypeVar

from sqlalchemy import func, insert, update
from sqlalchemy.orm import Session
from wireup import injectable

from src.imports.app.repositories import ImportJobRepository, ImportRowRepository
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportRow,
    ImportRowAction,
    ImportStatus,
)
from src.imports.infra.mappers import ImportJobMapper, ImportRowMapper
from src.imports.infra.models import ImportJobModel, ImportRowModel
from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository

# Rows per INSERT when a file is stored
INSERT_CHUNK = 1000

T = TypeVar("T")


def chunks(items: Iterable[T], size: int) -> Iterator[list[T]]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


@injectable(lifetime="scoped", as_type=ImportJobRepository)
class SqlAlchemyImportJobRepository(
    SqlAlchemyRepository[ImportJob], ImportJobRepository
):
    __model__ = ImportJobModel

    def __init__(self, session: Session, mapper: ImportJobMapper):
        super().__init__(session, mapper)

    def lock_for_run(self, job_id: int) -> ImportJob | None:
        model = (
            self._query()
            .filter(ImportJobModel.id == job_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        return self.mapper.to_entity(model)

    def page(
        self,
        kind: ImportKind | None,
        status: ImportStatus | None,
        limit: int,
        offset: int,
    ) -> dict:
        criteria = []
        if kind is not None:
            criteria.append(ImportJobModel.kind == kind.value)
        if status is not None:
            criteria.append(ImportJobModel.status == status.value)
        query = self._query().filter(*criteria)
        total = query.with_entities(func.count(ImportJobModel.id)).scalar() or 0
        models = (
            query.order_by(ImportJobModel.id.desc()).limit(limit).offset(offset).all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model) for model in models],
        }


@injectable(lifetime="scoped", as_type=ImportRowRepository)
class SqlAlchemyImportRowRepository(
    SqlAlchemyRepository[ImportRow], ImportRowRepository
):
    __model__ = ImportRowModel

    def __init__(self, session: Session, mapper: ImportRowMapper):
        super().__init__(session, mapper)

    def add_many(self, rows: Iterable[ImportRow]) -> None:
        # A Core INSERT skips `assign_tenant`: the tenant goes in each row
        tenant_id = require_tenant("writing ImportRowModel").tenant_id
        for chunk in chunks(rows, INSERT_CHUNK):
            self.session.execute(
                insert(ImportRowModel),
                [{**self.mapper.to_dict(row), "tenant_id": tenant_id} for row in chunk],
            )

    def after(self, job_id: int, row_number: int, limit: int) -> list[ImportRow]:
        models = (
            self._query()
            .filter(
                ImportRowModel.job_id == job_id,
                ImportRowModel.row_number > row_number,
            )
            .order_by(ImportRowModel.row_number)
            .limit(limit)
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]

    def record_results(
        self, results: Iterable[tuple[int, ImportRowAction, int | None]]
    ) -> None:
        values = [
            {"id": row_id, "action": action.value, "record_id": record_id}
            for row_id, action, record_id in results
        ]
        if values:
            # Bulk UPDATE by primary key: rows the batch loaded for this tenant
            self.session.execute(update(ImportRowModel), values)

    def page(
        self, job_id: int, action: ImportRowAction | None, limit: int, offset: int
    ) -> dict:
        query = self._query().filter(ImportRowModel.job_id == job_id)
        if action is not None:
            query = query.filter(ImportRowModel.action == action.value)
        total = query.with_entities(func.count(ImportRowModel.id)).scalar() or 0
        models = (
            query.order_by(ImportRowModel.row_number).limit(limit).offset(offset).all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model) for model in models],
        }

    def with_errors(self, job_id: int) -> list[ImportRow]:
        models = (
            self._query()
            .filter(
                ImportRowModel.job_id == job_id,
                ImportRowModel.action == ImportRowAction.ERROR.value,
            )
            .order_by(ImportRowModel.row_number)
            .all()
        )
        return [self.mapper.to_entity(model) for model in models]
