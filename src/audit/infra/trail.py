import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session
from wireup import injectable

from src.audit.infra.models import AuditLogModel
from src.shared.app.audit import AuditAction, AuditTrail
from src.shared.domain.tenant import require_tenant
from src.shared.infra.logging import is_sensitive_key

REQUEST_ID_KEY = "http.request.id"  # bound by RequestIdMiddleware


@injectable(lifetime="scoped", as_type=AuditTrail)
class SqlAlchemyAuditTrail(AuditTrail):
    """Writes the entry with the request's session: it commits or rolls back
    with the operation. Without a tenant context it fails, like the outbox."""

    def __init__(self, session: Session):
        self.session = session

    def record(
        self,
        action: AuditAction,
        resource_id: int | None,
        *,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        branch_id: int | None = None,
    ) -> None:
        context = require_tenant("writing to the audit log")
        self.session.add(
            AuditLogModel(
                tenant_id=context.tenant_id,
                actor_user_id=context.user_id,
                actor_name=context.user_name,
                action=action.value,
                resource_type=action.resource,
                resource_id=resource_id,
                branch_id=branch_id if branch_id is not None else context.branch_id,
                source=context.source.value,
                request_id=structlog.contextvars.get_contextvars().get(REQUEST_ID_KEY),
                before=_values(before),
                after=_values(after),
            )
        )
        self.session.flush()


def _values(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return json.loads(json.dumps(_without_secrets(values), default=_json_default))


def _without_secrets(value: Any) -> Any:
    """A sensitive key never reaches the log, even if a handler passes it"""
    if isinstance(value, Mapping):
        return {
            key: _without_secrets(item)
            for key, item in value.items()
            if not is_sensitive_key(key)
        }
    if isinstance(value, list | tuple):
        return [_without_secrets(item) for item in value]
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):  # datetime included
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")
