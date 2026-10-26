"""`Idempotency-Key` against PostgreSQL (S3.1): a POS operation sent again, in
sequence or at the same time, takes effect once and answers the same; the key
with another request is rejected; a failed attempt leaves it free."""

import os
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.auth.domain.entities import Role
from src.shared.domain.exceptions import IdempotencyInProgressError
from src.shared.domain.tenant import TenantContext, TenantSource, use_tenant
from src.shared.infra.database import create_session_maker, worker_session_maker
from src.shared.infra.idempotency.models import COMPLETED, IdempotencyKeyModel
from src.shared.infra.idempotency.purge import purge_expired
from src.shared.infra.idempotency.requests import (
    REPLAYED_HEADER,
    Idempotency,
    IdempotentRequest,
    request_hash,
)
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    concurrently,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
    with_key,
)
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant

QUICK = "/api/pos/sales/quick"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def api(client, auth_headers, terminal) -> Api:
    return Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))


@pytest.fixture
def manager(client, auth_headers, terminal) -> Api:
    return Api(client, at_terminal(auth_headers(Role.MANAGER), terminal))


@pytest.fixture
def product(admin_api, shelf) -> dict:
    """Priced at 10.00 plus VAT 15%, with 10 units on the terminal's shelf"""
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, shelf["id"])
    return product


@pytest.fixture
def shift(api) -> dict:
    return api.post("/api/pos/shifts/open", {"openingBalance": "100.00"})


def _checkout(product_id: int, quantity: int = 1) -> dict:
    return {
        "items": [{"productId": product_id, "quantity": quantity}],
        "payments": [{"amount": f"{11.5 * quantity:.2f}", "paymentMethod": "CASH"}],
    }


def _stock(admin_api: Api, product_id: int) -> int:
    rows = admin_api.get("/api/admin/stock", params={"productId": product_id})
    return sum(row["quantity"] for row in rows)


def _sales(admin_api: Api) -> list[dict]:
    return admin_api.get("/api/admin/sales")


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["errors"][0]["code"]


# Repeated requests


def test_a_repeated_quick_sale_answers_the_same_and_charges_once(
    client, api, admin_api, product, shift
):
    headers = with_key(api.headers)

    first = client.post(QUICK, json=_checkout(product["id"], 2), headers=headers)
    again = client.post(QUICK, json=_checkout(product["id"], 2), headers=headers)

    assert (first.status_code, again.status_code) == (201, 201)
    # Byte for byte what the first one answered, including its meta
    assert again.content == first.content
    assert again.headers[REPLAYED_HEADER] == "true"
    assert REPLAYED_HEADER not in first.headers
    assert len(_sales(admin_api)) == 1
    assert _stock(admin_api, product["id"]) == 8
    assert first.json()["data"]["number"] == "V-001-000001"
    # The next operation is another sale, with the next number
    assert api.post(QUICK, _checkout(product["id"]))["number"] == "V-001-000002"


def test_concurrent_quick_sales_with_one_key_make_one_sale(
    api, admin_api, product, shift
):
    headers = with_key(api.headers)

    def checkout(client: TestClient):
        return client.post(QUICK, json=_checkout(product["id"]), headers=headers)

    responses = concurrently(checkout, checkout, checkout)

    assert [r.status_code for r in responses] == [201, 201, 201]
    assert len({r.content for r in responses}) == 1
    assert sorted(r.headers.get(REPLAYED_HEADER, "") for r in responses) == [
        "",
        "true",
        "true",
    ]
    assert len(_sales(admin_api)) == 1
    assert _stock(admin_api, product["id"]) == 9


def test_the_key_of_another_request_is_rejected(client, api, admin_api, product, shift):
    headers = with_key(api.headers)
    client.post(QUICK, json=_checkout(product["id"]), headers=headers)

    other_body = client.post(QUICK, json=_checkout(product["id"], 2), headers=headers)
    other_route = client.post(
        f"/api/pos/shifts/{shift['id']}/cash-movements",
        json={"type": "OUT", "amount": "5.00"},
        headers=headers,
    )

    assert _error(other_body) == (422, "IDEMPOTENCY_KEY_REUSED")
    assert _error(other_route) == (422, "IDEMPOTENCY_KEY_REUSED")
    assert len(_sales(admin_api)) == 1
    assert _stock(admin_api, product["id"]) == 9
    assert api.get(f"/api/pos/shifts/{shift['id']}/cash-movements") == []


def test_a_failed_attempt_leaves_the_key_free(client, api, admin_api, product, shift):
    headers = with_key(api.headers)

    failed = client.post(QUICK, json=_checkout(product["id"], 11), headers=headers)
    retried = client.post(QUICK, json=_checkout(product["id"]), headers=headers)
    again = client.post(QUICK, json=_checkout(product["id"]), headers=headers)

    assert _error(failed) == (400, "INSUFFICIENT_STOCK")
    # The error rolled back with its reservation: the corrected request runs
    assert retried.status_code == 201
    assert again.content == retried.content
    assert len(_sales(admin_api)) == 1
    assert _stock(admin_api, product["id"]) == 9


ROUTES = [
    "/api/pos/sales",
    QUICK,
    "/api/pos/sales/1/confirm",
    "/api/pos/sales/1/payments",
    "/api/pos/refunds",
    "/api/pos/refunds/1/process",
    "/api/pos/shifts/1/cash-movements",
]


@pytest.mark.parametrize("path", ROUTES)
def test_a_pos_operation_without_its_key_is_rejected(
    client, api, manager, admin_api, path
):
    # Processing a refund is the manager's
    caller = manager if path.endswith("/process") else api
    response = client.post(path, json={}, headers=caller.headers)

    assert _error(response) == (422, "IDEMPOTENCY_KEY_REQUIRED")
    assert "Idempotency-Key" in response.json()["errors"][0]["message"]
    assert _sales(admin_api) == []


def test_every_pos_operation_takes_effect_once(
    client, api, manager, admin_api, product, shift
):
    def twice(caller: Api, path: str, body: dict | None = None) -> dict:
        headers = with_key(caller.headers)
        first = client.post(path, json=body, headers=headers)
        again = client.post(path, json=body, headers=headers)
        assert first.is_success, first.text
        assert again.content == first.content
        return first.json()["data"]

    sale = twice(api, "/api/pos/sales", {"isFinalConsumer": True})
    api.post(
        f"/api/pos/sales/{sale['id']}/items",
        {"productId": product["id"], "quantity": 1, "unitPrice": "10.00"},
    )
    twice(
        api,
        f"/api/pos/sales/{sale['id']}/payments",
        {"amount": "11.50", "paymentMethod": "CASH"},
    )
    confirmed = twice(api, f"/api/pos/sales/{sale['id']}/confirm")
    twice(
        api,
        f"/api/pos/shifts/{shift['id']}/cash-movements",
        {"type": "OUT", "amount": "5.00", "reason": "Cambio"},
    )
    [item] = api.get(f"/api/pos/sales/{sale['id']}/items")
    refund = twice(
        api,
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
        },
    )
    processed = twice(
        manager,
        f"/api/pos/refunds/{refund['id']}/process",
        {"payments": [{"amount": "11.50", "paymentMethod": "CASH"}]},
    )

    assert len(_sales(admin_api)) == 1
    assert len(api.get(f"/api/pos/sales/{sale['id']}/payments")) == 1
    assert confirmed["number"] == "V-001-000001"
    assert len(api.get(f"/api/pos/shifts/{shift['id']}/cash-movements")) == 1
    assert len(manager.get("/api/pos/refunds")) == 1
    assert processed["number"] == "D-001-000001"
    # Out once with the sale, back once with the refund
    assert _stock(admin_api, product["id"]) == 10
    summary = api.get(f"/api/pos/shifts/{shift['id']}/cash-summary")
    assert (summary["cashSales"], summary["cashRefunds"]) == (11.5, 11.5)


# Waiting for the request with the key


class Created(BaseModel):
    sale_id: int


@pytest.fixture(scope="module")
def app_sessions(pg_engine) -> Iterator[sessionmaker[Session]]:
    """Sessions like the requests': faclab_app, under row-level security"""
    factory = create_session_maker(os.environ["DATABASE_URL"])
    yield factory
    factory.kw["bind"].dispose()


def _request() -> IdempotentRequest:
    return IdempotentRequest(
        key=uuid4(),
        method="POST",
        path=QUICK,
        request_hash=request_hash("POST", QUICK, b'{"a":1}'),
        status_code=201,
    )


def _until_a_lock_waits(pg_engine: Engine) -> None:
    deadline = time.monotonic() + 5
    with pg_engine.connect() as conn:
        while conn.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")) == 0:
            assert time.monotonic() < deadline, "no request is waiting"
            time.sleep(0.02)


def test_a_request_waits_for_the_one_running_with_its_key(
    pg_engine, app_sessions, tenant
):
    request = _request()
    context = TenantContext(tenant, TenantSource.TASK)
    outcomes: dict[str, object] = {}

    def attempt(name: str, lock_wait: str) -> threading.Thread:
        def run() -> None:
            with use_tenant(context), app_sessions() as session:
                idempotency = Idempotency(session)
                idempotency.lock_wait = lock_wait
                try:
                    outcomes[name] = idempotency.run(
                        request, lambda: Created(sale_id=2)
                    )
                    session.commit()
                except IdempotencyInProgressError as exc:
                    outcomes[name] = exc

        thread = threading.Thread(target=run)
        thread.start()
        return thread

    waiting: list[threading.Thread] = []

    def respond() -> Created:
        # While this request runs, one that can't wait gives up and one that
        # can waits for it
        attempt("impatient", "100ms").join()
        waiting.append(attempt("patient", "10s"))
        _until_a_lock_waits(pg_engine)
        return Created(sale_id=1)

    with use_tenant(context), app_sessions() as session:
        Idempotency(session).run(request, respond)
        session.commit()
    waiting[0].join(timeout=10)

    assert isinstance(outcomes["impatient"], IdempotencyInProgressError)
    patient = outcomes["patient"]
    assert isinstance(patient, JSONResponse)
    assert patient.body == b'{"sale_id":1}'


def test_each_tenant_has_its_own_keys(pg_engine, app_sessions, tenant):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    request = _request()
    calls: list[UUID] = []

    for tenant_id in (tenant, other):

        def respond(tenant_id: UUID = tenant_id) -> Created:
            calls.append(tenant_id)
            return Created(sale_id=len(calls))

        with (
            use_tenant(TenantContext(tenant_id, TenantSource.TASK)),
            app_sessions() as session,
        ):
            Idempotency(session).run(request, respond)
            session.commit()

    assert calls == [tenant, other]


def test_the_purge_deletes_the_old_keys_of_every_tenant(
    pg_engine, app_sessions, tenant
):
    other = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    now = datetime.now()

    def add(tenant_id: UUID, age: timedelta) -> None:
        with (
            use_tenant(TenantContext(tenant_id, TenantSource.TASK)),
            app_sessions() as session,
        ):
            session.add(
                IdempotencyKeyModel(
                    key=uuid4(),
                    method="POST",
                    path=QUICK,
                    request_hash="h",
                    status=COMPLETED,
                    created_at=now - age,
                )
            )
            session.commit()

    add(tenant, timedelta(hours=30))
    add(other, timedelta(hours=25))
    add(other, timedelta(hours=1))

    # As faclab_worker: it sees every tenant's rows
    deleted = purge_expired(worker_session_maker(), now - timedelta(hours=24))

    assert deleted == 2
    with Session(bind=pg_engine) as session:
        kept = session.scalars(select(IdempotencyKeyModel.tenant_id)).all()
        assert kept == [other]
        assert session.scalar(select(func.count(IdempotencyKeyModel.id))) == 1
