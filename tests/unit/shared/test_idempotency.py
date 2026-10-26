"""`Idempotency-Key` (S3.1): the header dependency and the reservation, on
SQLite. The waits between concurrent requests run on PostgreSQL
(`tests/integration/postgres/test_idempotency.py`)."""

import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from config import config
from src.shared.domain.exceptions import (
    IdempotencyInProgressError,
    IdempotencyKeyReusedError,
)
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.idempotency.models import (
    COMPLETED,
    IN_PROGRESS,
    IdempotencyKeyModel,
)
from src.shared.infra.idempotency.purge import purge_expired
from src.shared.infra.idempotency.requests import (
    REPLAYED_HEADER,
    Idempotency,
    IdempotentRequest,
    idempotent_request,
    request_hash,
)
from src.shared.infra.middlewares import ErrorHandlingMiddleware
from src.tenancy.infra.models import TenantModel
from tests.conftest import TEST_TENANT_ID
from tests.sqlite import sqlite_session

OTHER_TENANT = UUID("00000000-0000-4000-8000-00000000000b")


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.post("/things/{thing_id}", status_code=201)
    def create(
        thing_id: int,
        request: IdempotentRequest | None = Depends(idempotent_request),
    ) -> dict:
        return {"request": None if request is None else asdict(request)}

    return app


def _post(key: str | None = None, path: str = "/things/7", **kwargs):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return TestClient(_app()).post(path, headers=headers, **kwargs)


def _error(response) -> tuple[int, str, str]:
    error = response.json()["errors"][0]
    return response.status_code, error["code"], error["message"]


# The header


def test_a_route_without_the_key_is_rejected_with_a_clear_message():
    status, code, message = _error(_post(json={"a": 1}))

    assert (status, code) == (422, "IDEMPOTENCY_KEY_REQUIRED")
    assert "Idempotency-Key" in message
    assert "every retry" in message


@pytest.mark.parametrize("key", ["", "abc", "123", "not-a-uuid-at-all"])
def test_a_key_that_is_not_a_uuid_is_rejected(key):
    assert _error(_post(key))[:2] == (422, "INVALID_IDEMPOTENCY_KEY")


def test_the_request_carries_its_key_route_and_status():
    key = uuid4()

    request = _post(str(key), json={"a": 1}).json()["request"]

    assert request["key"] == str(key)
    assert (request["method"], request["path"], request["status_code"]) == (
        "POST",
        "/things/7",
        201,
    )
    assert request["request_hash"] == request_hash("POST", "/things/7", b'{"a": 1}')


def test_with_the_requirement_off_a_request_without_key_runs_as_is(monkeypatch):
    monkeypatch.setattr(config, "IDEMPOTENCY_KEY_REQUIRED", False)

    assert _post(json={"a": 1}).json() == {"request": None}
    # A key that comes is still honored
    assert _post(str(uuid4()), json={"a": 1}).json()["request"] is not None


def test_the_hash_ignores_how_the_json_is_formatted():
    compact = request_hash("POST", "/s", b'{"b":[1,2],"a":"x"}')

    assert request_hash("POST", "/s", b'{ "a": "x",\n "b": [1, 2] }') == compact
    assert request_hash("POST", "/s", b'{"a":"x","b":[2,1]}') != compact
    assert request_hash("POST", "/t", b'{"b":[1,2],"a":"x"}') != compact
    assert request_hash("PUT", "/s", b'{"b":[1,2],"a":"x"}') != compact
    assert request_hash("POST", "/s", b"") == request_hash("POST", "/s", b"  ")


def test_two_bodies_with_other_key_order_get_the_same_hash():
    key = str(uuid4())
    first = _post(key, content='{"a": 1, "b": 2}').json()["request"]
    second = _post(key, content='{"b":2,"a":1}').json()["request"]

    assert first["request_hash"] == second["request_hash"]


# The reservation


class Created(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    sale_id: int
    total: float


@pytest.fixture
def session(in_tenant) -> Iterator[Session]:
    db = sqlite_session([IdempotencyKeyModel])
    db.add(TenantModel(id=OTHER_TENANT, ruc="1799999991001", legal_name="Otra"))
    db.commit()
    yield db
    db.close()


def _request(key: UUID | None = None, body: bytes = b'{"a":1}') -> IdempotentRequest:
    path = "/api/pos/sales/quick"
    return IdempotentRequest(
        key=key or uuid4(),
        method="POST",
        path=path,
        request_hash=request_hash("POST", path, body),
        status_code=201,
    )


class Counter:
    def __init__(self):
        self.calls = 0

    def __call__(self) -> Created:
        self.calls += 1
        return Created(sale_id=self.calls, total=11.5)


def _rows(session: Session) -> list[IdempotencyKeyModel]:
    return list(session.scalars(select(IdempotencyKeyModel)))


def test_the_first_request_runs_and_stores_its_response(session):
    respond = Counter()

    response = Idempotency(session).run(_request(), respond)
    session.commit()

    assert response == Created(sale_id=1, total=11.5)
    [row] = _rows(session)
    assert (row.status, row.response_status) == (COMPLETED, 201)
    # As FastAPI serializes it: by alias
    assert row.response_body == {"saleId": 1, "total": 11.5}
    assert row.tenant_id == TEST_TENANT_ID


def test_a_repeated_request_gets_the_stored_response_without_running(session):
    respond = Counter()
    request = _request()
    Idempotency(session).run(request, respond)
    session.commit()

    replay = Idempotency(session).run(request, respond)

    assert respond.calls == 1
    assert isinstance(replay, JSONResponse)
    assert replay.status_code == 201
    assert json.loads(bytes(replay.body)) == {"saleId": 1, "total": 11.5}
    assert replay.headers[REPLAYED_HEADER] == "true"
    assert len(_rows(session)) == 1


def test_the_key_with_another_body_is_rejected(session):
    key = uuid4()
    Idempotency(session).run(_request(key), Counter())
    session.commit()

    with pytest.raises(IdempotencyKeyReusedError):
        Idempotency(session).run(_request(key, b'{"a":2}'), Counter())


def test_a_failed_request_leaves_the_key_free(session):
    request = _request()

    def fail() -> Created:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        Idempotency(session).run(request, fail)
    # The request scope rolls back on any error
    session.rollback()
    assert _rows(session) == []

    respond = Counter()
    Idempotency(session).run(request, respond)
    assert respond.calls == 1


def test_a_committed_reservation_without_response_is_in_progress(session):
    request = _request()
    session.add(
        IdempotencyKeyModel(
            key=request.key,
            method=request.method,
            path=request.path,
            request_hash=request.request_hash,
            status=IN_PROGRESS,
        )
    )
    session.commit()

    with pytest.raises(IdempotencyInProgressError):
        Idempotency(session).run(request, Counter())


def test_without_a_key_the_request_runs_and_stores_nothing(session):
    respond = Counter()

    Idempotency(session).run(None, respond)
    Idempotency(session).run(None, respond)

    assert respond.calls == 2
    assert _rows(session) == []


def test_each_tenant_has_its_own_keys(session):
    request = _request()
    Idempotency(session).run(request, Counter())
    session.commit()

    respond = Counter()
    with use_tenant(TenantContext(OTHER_TENANT, TenantSource.TASK)):
        Idempotency(session).run(request, respond)
        session.commit()

    assert respond.calls == 1
    assert {row.tenant_id for row in _rows(session)} == {TEST_TENANT_ID, OTHER_TENANT}


# The purge


def test_the_purge_deletes_the_old_keys_of_every_tenant(session):
    now = datetime.now()

    def add(created_at: datetime) -> None:
        session.add(
            IdempotencyKeyModel(
                key=uuid4(),
                method="POST",
                path="/p",
                request_hash="h",
                status=COMPLETED,
                created_at=created_at,
            )
        )
        session.flush()

    add(now - timedelta(hours=30))
    add(now - timedelta(hours=1))
    with use_tenant(TenantContext(OTHER_TENANT, TenantSource.TASK)):
        add(now - timedelta(hours=25))
    session.commit()

    deleted = purge_expired(
        sessionmaker(bind=session.get_bind()), now - timedelta(hours=24)
    )

    assert deleted == 2
    session.expire_all()
    [kept] = _rows(session)
    assert kept.created_at == now - timedelta(hours=1)
