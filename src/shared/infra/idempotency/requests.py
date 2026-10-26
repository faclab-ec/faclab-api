"""`Idempotency-Key` (S3.1): a POST that creates a document or moves money runs
once per key, and sending it again answers what the first one answered.

The route reserves the key in the request's own transaction, runs the command
and stores the response in that same transaction:

- a request whose key is reserved by one still running waits for it (up to
  `Idempotency.lock_wait`, then 409 `IDEMPOTENCY_IN_PROGRESS`) and gets its
  response, with `Idempotent-Replayed: true`;
- the same key with another method, path or body answers 422
  `IDEMPOTENCY_KEY_REUSED`;
- a request that fails rolls back with its reservation: errors are never
  stored and the key stays free for a retry, which runs again because the
  failed one left nothing behind.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

import structlog
from fastapi import Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from wireup import injectable

from config import config
from src.shared.domain.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    InvalidIdempotencyKeyError,
)
from src.shared.domain.tenant import require_tenant
from src.shared.infra.idempotency.models import (
    COMPLETED,
    IN_PROGRESS,
    IdempotencyKeyModel,
)
from src.shared.infra.tenant import tenant_criteria

IDEMPOTENCY_HEADER = "Idempotency-Key"
# On a response repeated from a previous request with the key
REPLAYED_HEADER = "Idempotent-Replayed"

_LOCK_NOT_AVAILABLE = "55P03"

logger = structlog.get_logger(__name__)

R = TypeVar("R", bound=BaseModel)


@dataclass(frozen=True)
class IdempotentRequest:
    key: UUID
    method: str
    path: str
    request_hash: str
    # The route's status code, stored with the response it repeats
    status_code: int


def request_hash(method: str, path: str, body: bytes) -> str:
    """sha256 of the request: its method, its path (with the ids) and its body
    as canonical JSON, so the same request hashes the same however its client
    formats the JSON"""
    digest = hashlib.sha256(f"{method} {path}\n".encode())
    digest.update(_canonical(body))
    return digest.hexdigest()


def _canonical(body: bytes) -> bytes:
    if not body.strip():
        return b""
    try:
        value = json.loads(body)
    except ValueError:
        return body
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


async def idempotent_request(
    request: Request,
    key: str | None = Header(
        None,
        alias=IDEMPOTENCY_HEADER,
        description=(
            "A UUID generated once per operation and resent on every retry of it: "
            "the operation runs once and a retry gets the same response "
            "(`IDEMPOTENCY_KEY_REQUIRED`, 422, without it)"
        ),
    ),
) -> IdempotentRequest | None:
    """The key of an idempotent route (`IDEMPOTENCY_KEY_REQUIRED` without it,
    unless `IDEMPOTENCY_KEY_REQUIRED` is off: then the request runs as is)"""
    if key is None:
        if config.IDEMPOTENCY_KEY_REQUIRED:
            raise IdempotencyKeyRequiredError()
        return None
    try:
        value = UUID(key.strip())
    except ValueError:
        raise InvalidIdempotencyKeyError() from None
    route = request.scope.get("route")
    return IdempotentRequest(
        key=value,
        method=request.method,
        path=request.url.path,
        # FastAPI already read the body and Starlette keeps it
        request_hash=request_hash(
            request.method, request.url.path, await request.body()
        ),
        status_code=getattr(route, "status_code", None) or 200,
    )


@injectable(lifetime="scoped")
class Idempotency:
    """Runs an idempotent route once per key of the tenant, in the request's
    transaction (see the module)"""

    # How long a request waits for another one with its key (PostgreSQL)
    lock_wait = "10s"

    def __init__(self, session: Session):
        self.session = session

    def run(
        self, request: IdempotentRequest | None, respond: Callable[[], R]
    ) -> R | JSONResponse:
        """`respond()` once per key: a repeated key gets the stored response"""
        if request is None:
            return respond()
        stored = self._reserve(request)
        if stored is not None:
            return stored
        response = respond()
        self._complete(request, response)
        return response

    def _reserve(self, request: IdempotentRequest) -> JSONResponse | None:
        """None when the key is this request's; the stored response when an
        earlier request with it committed"""
        values = {
            "tenant_id": require_tenant("reserving an idempotency key").tenant_id,
            "key": request.key,
            "method": request.method,
            "path": request.path,
            "request_hash": request.request_hash,
            "status": IN_PROGRESS,
        }
        dialect = postgresql if self._on_postgresql() else sqlite
        statement = (
            dialect.insert(IdempotencyKeyModel)
            .values(**values)
            .on_conflict_do_nothing(index_elements=("tenant_id", "key"))
            .returning(IdempotencyKeyModel.id)
        )
        if self._insert(statement) is not None:
            return None

        stored = self.session.execute(
            select(
                IdempotencyKeyModel.request_hash,
                IdempotencyKeyModel.status,
                IdempotencyKeyModel.response_status,
                IdempotencyKeyModel.response_body,
            ).where(
                *tenant_criteria(IdempotencyKeyModel),
                IdempotencyKeyModel.key == request.key,
            )
        ).one()
        if stored.request_hash != request.request_hash:
            raise IdempotencyKeyReusedError()
        if stored.status != COMPLETED or stored.response_status is None:
            raise IdempotencyInProgressError()
        # A retry that the first attempt already answered: worth seeing
        logger.info("idempotent_request_replayed", path=request.path)
        return JSONResponse(
            status_code=stored.response_status,
            content=stored.response_body,
            headers={REPLAYED_HEADER: "true"},
        )

    def _insert(self, statement) -> int | None:
        """The id of the new row, None when the key exists. On PostgreSQL a key
        reserved by a running transaction makes the INSERT wait for it to end,
        and `lock_timeout` bounds only that wait."""
        if not self._on_postgresql():
            return self.session.execute(statement).scalar_one_or_none()
        previous = self.session.execute(
            text("SELECT current_setting('lock_timeout')")
        ).scalar_one()
        self._set_lock_timeout(self.lock_wait)
        try:
            row_id = self.session.execute(statement).scalar_one_or_none()
        except OperationalError as exc:
            if getattr(exc.orig, "pgcode", None) == _LOCK_NOT_AVAILABLE:
                raise IdempotencyInProgressError() from exc
            raise
        self._set_lock_timeout(previous)
        return row_id

    def _set_lock_timeout(self, value: str) -> None:
        self.session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"), {"value": value}
        )

    def _complete(self, request: IdempotentRequest, response: BaseModel) -> None:
        # Serialized as FastAPI serializes the route's response model
        body = response.model_dump(mode="json", by_alias=True)
        self.session.execute(
            update(IdempotencyKeyModel)
            .where(
                *tenant_criteria(IdempotencyKeyModel),
                IdempotencyKeyModel.key == request.key,
            )
            .values(
                status=COMPLETED,
                response_status=request.status_code,
                response_body=body,
            )
            .execution_options(synchronize_session=False)
        )

    def _on_postgresql(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"
