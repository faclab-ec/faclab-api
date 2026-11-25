from sqlalchemy import func
from sqlalchemy.orm import Session
from wireup import injectable

from src.data_protection.app.repositories import ExportJobRepository
from src.data_protection.domain.entities import ExportJob, ExportStatus
from src.data_protection.infra.mappers import ExportJobMapper
from src.data_protection.infra.models import ExportJobModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=ExportJobRepository)
class SqlAlchemyExportJobRepository(
    SqlAlchemyRepository[ExportJob], ExportJobRepository
):
    __model__ = ExportJobModel

    def __init__(self, session: Session, mapper: ExportJobMapper):
        super().__init__(session, mapper)

    def in_progress(self) -> ExportJob | None:
        model = (
            self._query()
            .filter(
                ExportJobModel.status.in_(
                    [ExportStatus.QUEUED.value, ExportStatus.RUNNING.value]
                )
            )
            .order_by(ExportJobModel.id)
            .first()
        )
        return self.mapper.to_entity(model)

    def page(self, limit: int, offset: int) -> dict:
        query = self._query()
        total = query.with_entities(func.count(ExportJobModel.id)).scalar() or 0
        models = (
            query.order_by(ExportJobModel.id.desc()).limit(limit).offset(offset).all()
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.mapper.to_entity(model) for model in models],
        }
