"""Signed webhooks over PostgreSQL (S6.4): enqueued in the transaction of the
event, sent by the worker's dispatcher across tenants as faclab_worker, to a
local HTTPS receiver that checks the signatures as PUBLIC_API.md §7.2
publishes."""

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from src.shared.infra.database import worker_session_maker
from src.webhooks.infra.dispatcher import WebhookDispatcher
from src.webhooks.infra.http import WebhookSender
from src.webhooks.infra.secrets import secret_box
from src.webhooks.infra.stock_changes import flush_stock_changes
from src.webhooks.infra.urls import DnsUrlGuard
from tests.integration.postgres.api import (
    Api,
    make_branch,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
    with_key,
)
from tests.integration.postgres.public_api import integration_headers
from tests.integration.postgres.support import issue_headers
from tests.integration.postgres.tenants import OTHER_TENANT_RUC, ensure_tenant
from tests.webhook_receiver import Receiver, localhost_certificate
from tests.webhooks_kit import table_resolver

V1 = "/api/v1"
WEBHOOKS = "/api/admin/webhook-endpoints"
# A public address: registering it needs no DNS (the test points the endpoint
# at the local receiver afterwards, as the superuser)
PUBLIC_URL = "https://93.184.215.14/hooks"
CERTIFICATE = localhost_certificate()


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shop(admin_api) -> dict:
    """Branch 001 with an emission point and a location holding 10 hammers"""
    branch = make_branch(admin_api, "001")
    point = admin_api.post(
        "/api/admin/emission-points", {"branchId": branch["id"], "code": "002"}
    )
    warehouse = make_warehouse(admin_api, "BOD-001", branch["id"])
    location = make_location(admin_api, warehouse["id"], "GENERAL")
    product = make_product(admin_api, "MART-16", salePrice="10.00")
    make_movement(admin_api, product["id"], 10, location["id"], unitCost="6.00")
    return {
        "branch": branch["id"],
        "point": point["id"],
        "location": location["id"],
        "product": product["id"],
    }


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    server = Receiver(CERTIFICATE)
    yield server
    server.close()


def _sale(shop, quantity: str = "2", amount: str = "23.00") -> dict:
    return {
        "emissionPointId": shop["point"],
        "locationId": shop["location"],
        "externalReference": "WEB-100234",
        "items": [{"productId": shop["product"], "quantity": quantity}],
        "payments": [{"method": "TRANSFER", "amount": amount, "reference": "tx-1"}],
    }


def _rows(engine: Engine, sql: str, **params) -> list:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params))


def _deliveries(engine: Engine, endpoint_id: int) -> list:
    return _rows(
        engine,
        "SELECT m.event_type, m.payload, m.xmin::text AS xmin, d.status "
        "FROM webhook_deliveries d JOIN webhook_messages m ON m.id = d.message_id "
        "WHERE d.endpoint_id = :endpoint ORDER BY d.id",
        endpoint=endpoint_id,
    )


def _point_at(engine: Engine, endpoint_id: int, url: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE webhook_endpoints SET url = :url WHERE id = :id"),
            {"url": url, "id": endpoint_id},
        )


def _dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher(
        worker_session_maker(),
        WebhookSender(
            DnsUrlGuard(
                resolver=table_resolver({"localhost": ["127.0.0.1"]}),
                allow_private=True,
            ),
            timeout=3.0,
            tls=CERTIFICATE.client_context(),
        ),
        secret_box(),
    )


def test_an_api_sale_is_told_in_its_transaction_but_not_to_its_own_client(
    client, admin_api, shop, pg_engine
):
    headers = integration_headers(admin_api, client)
    company = admin_api.post(
        WEBHOOKS,
        {"url": PUBLIC_URL, "eventTypes": ["sale.confirmed", "stock.changed"]},
    )
    own = client.post(
        f"{V1}/webhook-endpoints",
        headers=with_key(headers),
        json={
            "url": PUBLIC_URL,
            "eventTypes": ["sale.confirmed"],
            "excludeOwnChanges": True,
        },
    )
    assert own.status_code == 201, own.text

    sold = client.post(
        f"{V1}/sales",
        headers=with_key(headers) | {"X-Branch-Id": str(shop["branch"])},
        json=_sale(shop),
    )
    assert sold.status_code == 201, sold.text
    sale = sold.json()["data"]

    [(event_type, payload, message_xmin, status)] = _deliveries(
        pg_engine, company["id"]
    )
    assert (event_type, status) == ("sale.confirmed", "pending")
    # The sale as GET /api/v1/sales/{id} shows it
    shown = client.get(f"{V1}/sales/{sale['id']}", headers=headers).json()["data"]
    assert payload["data"] == {**shown, "updatedAt": payload["data"]["updatedAt"]}
    [(public_id,)] = _rows(pg_engine, "SELECT public_id FROM integration_clients")
    assert payload["originClientId"] == public_id
    # Written by the sale's own transaction
    [(sale_xmin,)] = _rows(
        pg_engine, "SELECT xmin::text FROM sales WHERE id = :id", id=sale["id"]
    )
    assert message_xmin == sale_xmin
    # The client's own sale doesn't come back to it
    assert _deliveries(pg_engine, own.json()["data"]["id"]) == []

    # stock.changed, grouped by the worker: 10 - 2 in the branch
    assert flush_stock_changes(worker_session_maker()) == 1
    stock = [
        row
        for row in _deliveries(pg_engine, company["id"])
        if row[0] == "stock.changed"
    ]
    [(_, stock_payload, _, _)] = stock
    assert stock_payload["data"] == {
        "productId": shop["product"],
        "sku": "MART-16",
        "branchId": shop["branch"],
        "available": "8",
    }
    assert stock_payload["originClientId"] == public_id


def test_a_sale_that_fails_tells_nothing(client, admin_api, shop, pg_engine):
    headers = integration_headers(admin_api, client)
    company = admin_api.post(
        WEBHOOKS, {"url": PUBLIC_URL, "eventTypes": ["sale.confirmed"]}
    )

    failed = client.post(
        f"{V1}/sales",
        headers=with_key(headers) | {"X-Branch-Id": str(shop["branch"])},
        json=_sale(shop, quantity="100", amount="1150.00"),
    )

    assert failed.status_code == 400, failed.text
    assert failed.json()["errors"][0]["code"] == "INSUFFICIENT_STOCK"
    assert _deliveries(pg_engine, company["id"]) == []
    assert _rows(pg_engine, "SELECT id FROM webhook_stock_changes") == []


def test_a_private_url_is_refused_when_registered(admin_api, client):
    for url in (
        "https://10.0.0.5/hooks",
        "https://localhost/hooks",
        "http://93.184.215.14/",
    ):
        response = client.post(
            WEBHOOKS,
            headers=admin_api.headers,
            json={"url": url, "eventTypes": ["sale.confirmed"]},
        )
        assert response.status_code == 422, response.text
        assert response.json()["errors"][0]["code"] == "WEBHOOK_URL_NOT_ALLOWED"


def test_the_worker_sends_every_tenant_s_messages_signed(
    client, admin_api, pg_engine, receiver, tenant
):
    other_tenant = ensure_tenant(pg_engine, OTHER_TENANT_RUC)
    other_api = Api(
        client, issue_headers(pg_engine, tenant_id=other_tenant, username="admin-b")
    )
    endpoints = []
    for api in (admin_api, other_api):
        endpoint = api.post(
            WEBHOOKS, {"url": PUBLIC_URL, "eventTypes": ["sale.confirmed"]}
        )
        _point_at(pg_engine, endpoint["id"], receiver.url)
        receiver.secrets.append(
            api.get(f"{WEBHOOKS}/{endpoint['id']}/secret")["secret"]
        )
        api.post(f"{WEBHOOKS}/{endpoint['id']}/test")
        endpoints.append(endpoint["id"])

    outcomes = _dispatcher().run_once()

    assert sorted(o.endpoint_id for o in outcomes) == sorted(endpoints)
    assert {o.status for o in outcomes} == {"delivered"}
    assert len(receiver.received) == 2
    assert all(got.verified for got in receiver.received)
    tenants = {json.loads(got.body)["tenantId"] for got in receiver.received}
    assert tenants == {str(other_tenant), str(tenant)}
    # Each tenant sees its own history only
    for api, endpoint_id in zip((admin_api, other_api), endpoints, strict=True):
        [shown] = api.get(f"{WEBHOOKS}/{endpoint_id}/deliveries")
        assert (shown["status"], shown["responseStatus"]) == ("delivered", 204)


def test_a_down_endpoint_is_retried_and_its_failure_kept(
    admin_api, pg_engine, receiver
):
    receiver.status = 503
    endpoint = admin_api.post(
        WEBHOOKS, {"url": PUBLIC_URL, "eventTypes": ["sale.confirmed"]}
    )
    _point_at(pg_engine, endpoint["id"], receiver.url)
    admin_api.post(f"{WEBHOOKS}/{endpoint['id']}/test")

    [outcome] = _dispatcher().run_once()

    assert outcome.status == "pending"
    [shown] = admin_api.get(f"{WEBHOOKS}/{endpoint['id']}/deliveries")
    assert (shown["attempts"], shown["responseStatus"], shown["lastError"]) == (
        1,
        503,
        "HTTP 503",
    )
    assert shown["nextAttemptAt"] is not None
    assert admin_api.get(f"{WEBHOOKS}/{endpoint['id']}")["failingSince"] is not None
