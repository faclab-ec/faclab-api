from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session
from wireup import injectable

from src.auth.domain.scopes import Scope
from src.integrations.domain.entities import IntegrationClientStatus
from src.integrations.infra.models import IntegrationClientModel
from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository
from src.shared.infra.tenant import tenant_criteria
from src.webhooks.app.repositories import (
    WebhookDeliveryRepository,
    WebhookEndpointRepository,
    WebhookQueue,
)
from src.webhooks.domain.entities import (
    Subscriber,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
    WebhookEndpointStatus,
)
from src.webhooks.domain.types import WebhookEventType
from src.webhooks.infra.mappers import WebhookDeliveryMapper, WebhookEndpointMapper
from src.webhooks.infra.models import (
    WebhookDeliveryModel,
    WebhookEndpointModel,
    WebhookMessageModel,
)

# Where a transaction keeps the tenant's subscribers once read
_SUBSCRIBERS = "webhook_subscribers"


@injectable(lifetime="scoped", as_type=WebhookEndpointRepository)
class SqlAlchemyWebhookEndpointRepository(
    SqlAlchemyRepository[WebhookEndpoint], WebhookEndpointRepository
):
    __model__ = WebhookEndpointModel

    def __init__(self, session: Session, mapper: WebhookEndpointMapper):
        super().__init__(session, mapper)

    def page(
        self,
        owner_id: int | None,
        status: WebhookEndpointStatus | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[WebhookEndpoint], int]:
        criteria = []
        if owner_id is not None:
            criteria.append(WebhookEndpointModel.integration_client_id == owner_id)
        if status is not None:
            criteria.append(WebhookEndpointModel.status == status.value)
        endpoints = self.filter(criteria, order_by="id", limit=limit, offset=offset)
        total = self._query(func.count(WebhookEndpointModel.id)).filter(*criteria)
        return endpoints, total.scalar() or 0

    def of_owner(self, owner_id: int) -> list[WebhookEndpoint]:
        return self.filter(
            [WebhookEndpointModel.integration_client_id == owner_id], order_by="id"
        )

    def remove(self, endpoint_id: int) -> None:
        # By hand, not by the foreign key's cascade: the same on SQLite
        self.session.execute(
            delete(WebhookDeliveryModel).where(
                WebhookDeliveryModel.endpoint_id == endpoint_id,
                *tenant_criteria(WebhookDeliveryModel),
            )
        )
        self.delete(endpoint_id)


def _delivery_columns() -> tuple[Any, ...]:
    return (
        WebhookDeliveryModel.id,
        WebhookDeliveryModel.endpoint_id,
        WebhookMessageModel.public_id.label("message_id"),
        WebhookMessageModel.event_type,
        WebhookMessageModel.occurred_at,
        WebhookDeliveryModel.status,
        WebhookDeliveryModel.attempts,
        WebhookDeliveryModel.next_attempt_at,
        WebhookDeliveryModel.last_attempt_at,
        WebhookDeliveryModel.response_status,
        WebhookDeliveryModel.last_error,
        WebhookDeliveryModel.duration_ms,
        WebhookDeliveryModel.delivered_at,
        WebhookDeliveryModel.retried_at,
        WebhookDeliveryModel.created_at,
    )


@injectable(lifetime="scoped", as_type=WebhookDeliveryRepository)
class SqlAlchemyWebhookDeliveryRepository(
    SqlAlchemyRepository[WebhookDelivery], WebhookDeliveryRepository
):
    __model__ = WebhookDeliveryModel

    def __init__(self, session: Session, mapper: WebhookDeliveryMapper):
        super().__init__(session, mapper)

    def _described(self, *criteria: Any):
        return (
            select(*_delivery_columns())
            .join(
                WebhookMessageModel,
                WebhookMessageModel.id == WebhookDeliveryModel.message_id,
            )
            .where(
                *criteria,
                *tenant_criteria(WebhookDeliveryModel, WebhookMessageModel),
            )
        )

    def history(
        self,
        endpoint_id: int,
        since: datetime,
        status: WebhookDeliveryStatus | None,
        event_type: str | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[dict], int]:
        criteria: list[Any] = [
            WebhookDeliveryModel.endpoint_id == endpoint_id,
            WebhookDeliveryModel.created_at >= since,
        ]
        if status is not None:
            criteria.append(WebhookDeliveryModel.status == status.value)
        if event_type is not None:
            criteria.append(WebhookMessageModel.event_type == event_type)
        query = self._described(*criteria).order_by(WebhookDeliveryModel.id.desc())
        if limit is not None:
            query = query.limit(limit)
        if offset is not None:
            query = query.offset(offset)
        items = [dict(row._mapping) for row in self.session.execute(query)]
        total = self.session.scalar(
            select(func.count()).select_from(self._described(*criteria).subquery())
        )
        return items, total or 0

    def describe(self, delivery_id: int) -> dict | None:
        row = self.session.execute(
            self._described(WebhookDeliveryModel.id == delivery_id)
        ).first()
        return dict(row._mapping) if row is not None else None


@injectable(lifetime="scoped", as_type=WebhookQueue)
class SqlAlchemyWebhookQueue(WebhookQueue):
    def __init__(self, session: Session):
        self.session = session

    def subscribers(self) -> list[Subscriber]:
        transaction = self.session.get_transaction()
        cached = self.session.info.get(_SUBSCRIBERS)
        if cached is not None and cached[0] is transaction:
            return cached[1]
        subscribers = self._read_subscribers()
        self.session.info[_SUBSCRIBERS] = (transaction, subscribers)
        return subscribers

    def _read_subscribers(self) -> list[Subscriber]:
        rows = self.session.execute(
            select(
                WebhookEndpointModel.id,
                WebhookEndpointModel.event_types,
                WebhookEndpointModel.exclude_own_changes,
                WebhookEndpointModel.integration_client_id,
                IntegrationClientModel.status,
                IntegrationClientModel.scopes,
                IntegrationClientModel.branch_ids,
            )
            .outerjoin(
                IntegrationClientModel,
                (
                    IntegrationClientModel.id
                    == WebhookEndpointModel.integration_client_id
                )
                & (IntegrationClientModel.tenant_id == WebhookEndpointModel.tenant_id),
            )
            .where(
                WebhookEndpointModel.status == WebhookEndpointStatus.ACTIVE.value,
                *tenant_criteria(WebhookEndpointModel),
            )
            .order_by(WebhookEndpointModel.id)
        ).all()
        subscribers = []
        for row in rows:
            owner_id = row.integration_client_id
            if owner_id is not None and row.status != IntegrationClientStatus.ACTIVE:
                continue
            subscribers.append(
                Subscriber(
                    endpoint_id=row.id,
                    event_types=frozenset(
                        WebhookEventType(name)
                        for name in row.event_types
                        if name in WebhookEventType._value2member_map_
                    ),
                    exclude_own_changes=row.exclude_own_changes,
                    owner_id=owner_id,
                    owner_scopes=frozenset(
                        Scope(name)
                        for name in row.scopes or ()
                        if name in Scope._value2member_map_
                    ),
                    owner_branch_ids=(
                        frozenset(row.branch_ids) if row.branch_ids else None
                    ),
                )
            )
        return subscribers

    def client_public_id(self, client_id: int) -> str | None:
        return self.session.scalar(
            select(IntegrationClientModel.public_id).where(
                IntegrationClientModel.id == client_id,
                *tenant_criteria(IntegrationClientModel),
            )
        )

    def enqueue(
        self,
        public_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        origin_integration_id: int | None,
        endpoint_ids: Iterable[int],
    ) -> list[int]:
        tenant_id = require_tenant("enqueuing a webhook").tenant_id
        if occurred_at.tzinfo is not None:
            occurred_at = occurred_at.astimezone(UTC).replace(tzinfo=None)
        message = WebhookMessageModel(
            public_id=public_id,
            event_type=event_type,
            payload=payload,
            occurred_at=occurred_at,
            origin_integration_id=origin_integration_id,
        )
        self.session.add(message)
        self.session.flush()
        now = datetime.now()
        ids = self.session.scalars(
            insert(WebhookDeliveryModel).returning(WebhookDeliveryModel.id),
            [
                {
                    "tenant_id": tenant_id,
                    "message_id": message.id,
                    "endpoint_id": endpoint_id,
                    "status": WebhookDeliveryStatus.PENDING.value,
                    "attempts": 0,
                    "next_attempt_at": now,
                    "created_at": now,
                }
                for endpoint_id in endpoint_ids
            ],
        ).all()
        return list(ids)


def pending_criteria(now: datetime) -> list[Any]:
    """The deliveries due now"""
    return [
        WebhookDeliveryModel.status == WebhookDeliveryStatus.PENDING.value,
        or_(
            WebhookDeliveryModel.next_attempt_at.is_(None),
            WebhookDeliveryModel.next_attempt_at <= now,
        ),
    ]
