from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy.orm import Session
from wireup import injectable

from src.audit.infra.models import AuditLogModel
from src.shared.app.queries import Query, QueryHandler
from src.shared.infra.tenant import tenant_criteria


@dataclass
class ListAuditLogQuery(Query):
    from_date: date | None = None
    to_date: date | None = None
    actor_id: int | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: int | None = None
    branch_id: int | None = None
    limit: int = 50
    offset: int = 0


@injectable(lifetime="scoped")
class ListAuditLogQueryHandler(QueryHandler[ListAuditLogQuery, dict]):
    """The tenant's entries, newest first. The branch is only the `branchId`
    filter, not the request's `X-Branch-Id`."""

    def __init__(self, session: Session):
        self.session = session

    def _handle(self, query: ListAuditLogQuery) -> dict:
        q = self.session.query(AuditLogModel).filter(*tenant_criteria(AuditLogModel))

        if query.from_date is not None:
            q = q.filter(
                AuditLogModel.occurred_at >= datetime.combine(query.from_date, time.min)
            )
        if query.to_date is not None:
            q = q.filter(
                AuditLogModel.occurred_at <= datetime.combine(query.to_date, time.max)
            )
        if query.actor_id is not None:
            q = q.filter(AuditLogModel.actor_user_id == query.actor_id)
        if query.action is not None:
            q = q.filter(AuditLogModel.action == query.action)
        if query.resource_type is not None:
            q = q.filter(AuditLogModel.resource_type == query.resource_type)
        if query.resource_id is not None:
            q = q.filter(AuditLogModel.resource_id == query.resource_id)
        if query.branch_id is not None:
            q = q.filter(AuditLogModel.branch_id == query.branch_id)

        total = q.count()
        rows = (
            q.order_by(AuditLogModel.id.desc())
            .offset(query.offset)
            .limit(query.limit)
            .all()
        )

        return {
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "items": [
                {
                    "id": row.id,
                    "occurred_at": row.occurred_at,
                    "actor_user_id": row.actor_user_id,
                    "actor_name": row.actor_name,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "branch_id": row.branch_id,
                    "source": row.source,
                    "request_id": row.request_id,
                    "before": row.before,
                    "after": row.after,
                }
                for row in rows
            ],
        }
